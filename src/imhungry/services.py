"""Shared application behavior. HTTP and Strands call this layer independently."""

import base64
import hashlib
import json
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from .errors import AppError, Conflict, NotFound
from .models import (RECORDS, DateRange, Nutrition, StrategyCalculationRequest,
                     Recipe, FoodLookupRequest, FoodEstimateRequest, NutritionResult, EstimatedNutrition)
from .repository import Repository, Write, partition


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise AppError("validation", "Timestamp requires a timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def encode(value):
    return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")


def decode(value):
    try:
        if len(value) > 2000:
            raise ValueError()
        return json.loads(base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True))
    except (ValueError, TypeError, UnicodeError):
        raise AppError("validation", "Invalid resource reference or cursor") from None


def merge(old, patch):
    result = deepcopy(old)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def total_nutrition(entries):
    result = {}
    for field in Nutrition.model_fields:
        values = [e[field] for e in entries if field in e]
        if field in {"energy_kcal", "protein_g", "carbs_g", "fat_g"} or (entries and len(values) == len(entries)):
            result[field] = round(sum(values), 4)
    return result


class NutritionService:
    def __init__(self, repository: Repository, *, clock=None, provider=None):
        self.repo = repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.provider = provider

    def now(self):
        return utc(self.clock())

    def zone(self, user):
        profile = self.repo.get(user, "PROFILE")
        return ZoneInfo(profile.get("timezone", "UTC") if profile else "UTC")

    def today(self, user):
        return self.clock().astimezone(self.zone(user)).date()

    def _receipt(self, user, operation, key, payload):
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise AppError("idempotency_key", "Provide an idempotency key of 1 to 200 characters")
        receipt_key = "REQUEST#" + digest([operation, key])
        fingerprint = digest(payload)
        receipt = self.repo.get(user, receipt_key)
        if receipt:
            if receipt["payload_digest"] != fingerprint:
                raise Conflict("Idempotency key was used with a different payload")
            return receipt_key, fingerprint, receipt["result"]
        return receipt_key, fingerprint, None

    def _commit(self, user, writes, receipt_key, fingerprint, result):
        receipt = {"record_type": "request", "schema_version": 1, "created_at": self.now(),
                   "payload_digest": fingerprint, "result": result, "version": 1}
        if len(json.dumps(receipt).encode()) > 300_000:
            raise AppError("size_limit", "Resource exceeds the supported size")
        try:
            self.repo.transact(user, writes + [Write(receipt_key, receipt)])
        except Conflict:
            completed = self.repo.get(user, receipt_key)
            if completed and completed["payload_digest"] == fingerprint:
                return completed["result"]
            raise
        return result

    def key(self, kind, reference):
        prefix, _, _, timestamp = RECORDS[kind]
        if kind == "profile":
            return prefix
        if kind == "nutrition-strategies":
            return prefix + "#" + utc(reference)
        try:
            if timestamp:
                ident, day, slot = decode(reference)
                UUID(ident)
                date.fromisoformat(day)
                if kind == "planned-meals":
                    if slot not in {"breakfast", "lunch", "dinner", "snack", "other"}:
                        raise ValueError()
                else:
                    slot = utc(slot)
                return f"{prefix}#{day}#{slot}#{ident}"
            return f"{prefix}#{UUID(reference)}"
        except (ValueError, TypeError):
            raise AppError("validation", "Invalid resource reference") from None

    def public(self, item):
        hidden = {"PK", "SK", "GSI1PK", "GSI1SK", "invocation_id", "invocation_status", "pending_request", "has_snapshot"}
        return {k: deepcopy(v) for k, v in item.items() if k not in hidden}

    def get(self, user, kind, reference="profile"):
        item = self.repo.get(user, self.key(kind, reference))
        if item is None:
            if kind == "profile":
                return {"version": 0, "configured": False}
            raise NotFound()
        return self.public(item)

    def _domain(self, kind, item):
        model = RECORDS[kind][1]
        fields = {f.alias or name for name, f in model.model_fields.items()}
        return {k: deepcopy(v) for k, v in item.items() if k in fields}

    def _record(self, user, kind, payload, old=None):
        prefix, model, record_type, timestamp = RECORDS[kind]
        data = model.model_validate(payload).data()
        now = self.now()
        ident_field = {"recipes": "recipe_id", "saved-foods": "food_id", "behavior-patterns": "pattern_id",
                       "conversations": "conversation_id"}.get(kind, "entry_id")
        ident = old[ident_field] if old and ident_field in old else str(uuid4())
        item = {**data, "record_type": record_type, "schema_version": 1,
                "created_at": old["created_at"] if old else now,
                "updated_at": now, "version": old["version"] + 1 if old else 1}
        if kind == "profile":
            key, reference = prefix, "profile"
        elif kind == "nutrition-strategies":
            if data["calculation"]["method"] == "mifflin_st_jeor":
                inputs = data["calculation"]["inputs"]
                request = {"goal": data["goal"], "protein_g_per_kg": inputs.get("protein_g_per_kg", 1.6),
                           "fat_fraction": inputs.get("fat_fraction", .3)}
                if "hydration_ml" in data["targets"]:
                    request["hydration_ml"] = data["targets"]["hydration_ml"]
                calculated = self.calculate_strategy(user, request)
                if not calculated["complete"] or calculated["targets"] != data["targets"] or calculated["calculation"] != data["calculation"]:
                    raise AppError("calculation_changed", "Recalculate the strategy from current profile inputs before saving; manual targets must use user_provided provenance")
            item["effective_from"] = utc(data["effective_from"])
            key, reference = prefix + "#" + item["effective_from"], item["effective_from"]
        else:
            item[ident_field] = ident
            if timestamp:
                item[timestamp] = utc(data[timestamp])
                same_time = old and item[timestamp] == old[timestamp]
                day = old["local_date"] if same_time else datetime.fromisoformat(item[timestamp]).astimezone(self.zone(user)).date().isoformat()
                item["local_date"] = day
                slot = item["meal_slot"] if kind == "planned-meals" else item[timestamp]
                reference = encode([ident, day, slot])
                key = f"{prefix}#{day}#{slot}#{ident}"
            else:
                key, reference = prefix + "#" + ident, ident
        item["entry_ref"] = reference
        if kind == "food-log":
            food = item["food"]
            food["normalized_name"] = " ".join(food["display_name"].casefold().split())
            food["food_fingerprint"] = digest([food["normalized_name"], food["unit"].casefold()])
        if kind == "conversations":
            item.update(GSI1PK=partition(user), GSI1SK=now + "#" + ident)
        if kind == "recipes":
            item.update(self.calculate_recipe(data))
        if kind in {"planned-meals", "behavior-patterns"} and data.get("source_conversation_id"):
            self.get(user, "conversations", data["source_conversation_id"])
        if kind == "planned-meals":
            for meal_item in data["items"]:
                if meal_item.get("recipe_id"):
                    self.get(user, "recipes", meal_item["recipe_id"])
                if meal_item.get("saved_food_id"):
                    self.get(user, "saved-foods", meal_item["saved_food_id"])
            if data["completed_intake_entry_ids"]:
                # Link existing logged consumption; a status change never invents intake.
                known = {i["entry_id"] for i in self.records(user, "food-log", item["local_date"])}
                if not set(data["completed_intake_entry_ids"]) <= known:
                    raise NotFound()
        return key, item

    def create(self, user, kind, payload, request_id):
        receipt, fingerprint, previous = self._receipt(user, "create:" + kind, request_id, payload)
        if previous is not None:
            return previous
        key, item = self._record(user, kind, payload)
        return self._commit(user, [Write(key, item)], receipt, fingerprint, self.public(item))

    def update(self, user, kind, reference, patch, expected_version, request_id=None):
        if type(expected_version) is not int or expected_version < 0:
            raise AppError("validation", "Expected version must be a non-negative integer")
        if kind == "nutrition-strategies":
            raise AppError("immutable", "Append a new strategy revision")
        if not isinstance(patch, dict) or not patch:
            raise AppError("validation", "Provide a non-empty patch")
        receipt, fingerprint, previous = self._receipt(user, f"update:{kind}:{reference}",
            request_id or f"version:{expected_version}", [patch, expected_version])
        if previous is not None:
            return previous
        key = self.key(kind, reference)
        old = self.repo.get(user, key)
        if old is None and not (kind == "profile" and expected_version == 0):
            raise NotFound()
        if old and old["version"] != expected_version:
            raise Conflict()
        # Derived food fields must not become client-editable on a merged patch.
        domain = self._domain(kind, old) if old else {}
        if kind == "food-log":
            domain["food"].pop("normalized_name", None)
            domain["food"].pop("food_fingerprint", None)
        new_key, item = self._record(user, kind, merge(domain, patch), old)
        writes = [Write(key, item, expected_version)] if key == new_key else [Write(key, None, expected_version), Write(new_key, item)]
        return self._commit(user, writes, receipt, fingerprint, self.public(item))

    def delete(self, user, kind, reference, expected_version, request_id=None):
        if type(expected_version) is not int or expected_version < 1:
            raise AppError("validation", "Expected version must be a positive integer")
        receipt, fingerprint, previous = self._receipt(user, f"delete:{kind}:{reference}",
            request_id or f"version:{expected_version}", expected_version)
        if previous is not None:
            return previous
        key = self.key(kind, reference)
        if self.repo.get(user, key) is None:
            raise NotFound()
        return self._commit(user, [Write(key, None, expected_version)], receipt, fingerprint,
                            {"deleted": True, "entry_ref": reference})

    def records(self, user, kind, start_date=None, end_date=None):
        prefix, _, _, timestamp = RECORDS[kind]
        if timestamp:
            span = DateRange(start_date=start_date or self.today(user), end_date=end_date)
            lower, upper = f"{prefix}#{span.start_date}#", f"{prefix}#{span.end_date}#~"
        elif kind == "nutrition-strategies" and start_date:
            span = DateRange(start_date=start_date, end_date=end_date)
            zone = self.zone(user)
            lower = prefix + "#" + utc(datetime.combine(span.start_date, time.min, zone))
            upper = prefix + "#" + utc(datetime.combine(span.end_date, time.max, zone))
        else:
            lower, upper = prefix + "#", prefix + "#~"
        items = self.repo.query(user, "!" if kind == "conversations" else lower,
                                "~" if kind == "conversations" else upper,
                                reverse=kind == "conversations", index=kind == "conversations")
        return [self.public(item) for item in items]

    def list(self, user, kind, start_date=None, end_date=None, *, query=None, status=None, category=None, limit=50, cursor=None):
        if not 1 <= limit <= 100:
            raise AppError("validation", "Page size must be 1 to 100")
        scope = digest([user, kind, str(start_date), str(end_date), query, status, category])
        offset = 0
        if cursor:
            value = decode(cursor)
            if not isinstance(value, list) or len(value) != 2:
                raise AppError("validation", "Invalid cursor")
            cursor_scope, offset = value
            if cursor_scope != scope or type(offset) is not int or offset < 0:
                raise AppError("validation", "Cursor does not match this query")
        items = self.records(user, kind, start_date, end_date)
        if query:
            items = [i for i in items if query.casefold() in json.dumps(self._domain(kind, i)).casefold()]
        if status:
            items = [i for i in items if i.get("status") == status]
        if category:
            items = [i for i in items if i.get("category") == category]
        return {"items": items[offset:offset + limit], "next_cursor": encode([scope, offset + limit]) if offset + limit < len(items) else None}

    def current_strategy(self, user, on_date=None):
        day = date.fromisoformat(on_date) if isinstance(on_date, str) else on_date
        instant = self.clock() if day is None or day == self.today(user) else datetime.combine(day, time.max, self.zone(user))
        items = self.repo.query(user, "NUTRITION_STRATEGY#", "NUTRITION_STRATEGY#" + utc(instant), reverse=True, limit=1)
        return self.public(items[0]) if items else None

    def calculate_strategy(self, user, request):
        req = StrategyCalculationRequest.model_validate(request)
        profile = self.get(user, "profile")
        needed = [key for key in ("date_of_birth", "sex_for_bmr_equation", "height_cm", "activity_context") if not profile.get(key)]
        if needed:
            return {"complete": False, "missing_inputs": needed, "assumptions": [], "warnings": ["Complete the physical and activity inputs before calculating targets."]}
        born = date.fromisoformat(profile["date_of_birth"])
        today = self.today(user)
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        if not 18 <= age <= 100:
            raise AppError("calculation_scope", "Automatic target calculation supports adults aged 18 to 100")
        level = profile["activity_context"]["level"]
        multiplier = {"sedentary": 1.2, "lightly_active": 1.375, "moderately_active": 1.55, "very_active": 1.725, "extra_active": 1.9}[level]
        weight = req.goal.baseline_weight_kg
        bmr = 10 * weight + 6.25 * profile["height_cm"] - 5 * age + (5 if profile["sex_for_bmr_equation"] == "male" else -161)
        tdee = bmr * multiplier
        deficit = req.goal.desired_rate_kg_per_week * 7700 / 7
        energy = tdee - deficit
        protein = weight * req.protein_g_per_kg
        fat = energy * req.fat_fraction / 9
        carbs = (energy - protein * 4 - fat * 9) / 4
        if energy < 1200 or carbs < 0 or deficit > tdee * .25:
            raise AppError("calculation_scope", "Requested rate produces an unsupported target; choose a more gradual rate")
        targets = {"energy_kcal": round(energy), "protein_g": round(protein, 2), "carbs_g": round(carbs, 2), "fat_g": round(fat, 2)}
        if req.hydration_ml:
            targets["hydration_ml"] = req.hydration_ml
        return {"complete": True, "goal": req.goal.data(), "targets": targets,
                "calculation": {"method": "mifflin_st_jeor", "method_version": 1,
                    "inputs": {"age_years": age, "sex_for_equation": profile["sex_for_bmr_equation"], "height_cm": profile["height_cm"],
                               "weight_kg": weight, "activity_level": level, "activity_multiplier": multiplier,
                               "protein_g_per_kg": req.protein_g_per_kg, "fat_fraction": req.fat_fraction},
                    "results": {"bmr_kcal": round(bmr, 2), "tdee_kcal": round(tdee, 2)},
                    "assumptions": ["Activity multiplier is self-reported", "7700 kcal/kg is an approximate planning conversion"]},
                "warnings": ["Estimated adult starting targets; adjust using hunger, energy and progress, never compensatory restriction."]}

    def summary(self, user, start_date, end_date=None):
        span = DateRange(start_date=start_date, end_date=end_date)
        entries = self.records(user, "food-log", span.start_date, span.end_date)
        strategies = self._daily_strategies(user, span)
        days = []
        for offset in range((span.end_date - span.start_date).days + 1):
            day = span.start_date + timedelta(days=offset)
            foods = [e for e in entries if e["local_date"] == day.isoformat()]
            total = total_nutrition([e["nutrition"] for e in foods])
            strategy = strategies[str(day)]
            targets = strategy["targets"] if strategy else None
            days.append({"local_date": str(day), "totals": total, "entry_count": len(foods), "has_logged_intake": bool(foods),
                         "targets": targets, "remaining": {k: round(v - total[k], 4) for k, v in targets.items() if k in total} if targets else None})
        total = total_nutrition([e["nutrition"] for e in entries])
        return {"days": days, "totals": total, "averages_per_calendar_day": {k: round(v / len(days), 4) for k, v in total.items()},
                "logged_days": sum(d["has_logged_intake"] for d in days),
                "note": "Totals describe logged intake only; an unlogged day does not imply zero consumption."}

    def calculate_recipe(self, request):
        recipe = Recipe.model_validate(request)
        totals = total_nutrition([i.nutrition_for_quantity.data() for i in recipe.ingredients])
        return {"nutrition_total": totals,
                "nutrition_per_serving": {key: round(value / recipe.recipe_yield.servings, 4) for key, value in totals.items()},
                "calculation_version": 1}

    def frequent_foods(self, user, query=None, lookback_days=60):
        if type(lookback_days) is not int or not 1 <= lookback_days <= 366:
            raise AppError("validation", "Lookback must be 1 to 366 days")
        today = self.today(user)
        foods = self.records(user, "food-log", today - timedelta(days=lookback_days - 1), today)
        groups = {}
        for entry in foods:
            food = entry["food"]
            if query and query.casefold() not in food["display_name"].casefold():
                continue
            fingerprint = food["food_fingerprint"]
            group = groups.setdefault(fingerprint, {"food": food, "count": 0})
            group["count"] += 1
            group["latest_entry"] = entry
        return sorted(groups.values(), key=lambda item: (-item["count"], item["food"]["normalized_name"]))[:100]

    def hydration_summary(self, user, start_date, end_date=None):
        span = DateRange(start_date=start_date, end_date=end_date)
        entries = self.records(user, "hydration", span.start_date, span.end_date)
        strategies = self._daily_strategies(user, span)
        days = []
        for offset in range((span.end_date - span.start_date).days + 1):
            day = span.start_date + timedelta(days=offset)
            amount = sum(e["amount_ml"] for e in entries if e["local_date"] == str(day))
            strategy = strategies[str(day)]
            target = strategy["targets"].get("hydration_ml") if strategy else None
            days.append({"local_date": str(day), "amount_ml": amount, "target_ml": target,
                         "remaining_ml": target - amount if target is not None else None})
        total = sum(e["amount_ml"] for e in entries)
        return {"days": days, "total_ml": total, "average_ml_per_calendar_day": total / len(days)}

    def _daily_strategies(self, user, span):
        """Two bounded queries per period, rather than one query per day."""
        zone = self.zone(user)
        lower = "NUTRITION_STRATEGY#" + utc(datetime.combine(span.start_date, time.min, zone))
        upper = "NUTRITION_STRATEGY#" + utc(datetime.combine(span.end_date, time.max, zone))
        baseline = self.repo.query(user, "NUTRITION_STRATEGY#", lower, reverse=True, limit=1)
        revisions = baseline + self.repo.query(user, lower, upper)
        result = {}
        today, now = self.today(user), self.clock()
        for offset in range((span.end_date - span.start_date).days + 1):
            day = span.start_date + timedelta(days=offset)
            instant = now if day == today else datetime.combine(day, time.max, zone)
            applicable = [revision for revision in revisions if revision["effective_from"] <= utc(instant)]
            result[str(day)] = self.public(applicable[-1]) if applicable else None
        return result

    def meal_context(self, user, local_date, meal_type=None):
        summary = self.summary(user, local_date)
        planned = self.records(user, "planned-meals", local_date)
        if meal_type:
            planned = [m for m in planned if m["meal_slot"] == meal_type]
        return {"profile": self.get(user, "profile"), "strategy": self.current_strategy(user, local_date),
                "intake": self.records(user, "food-log", local_date), "nutrition": summary,
                "hydration": self.hydration_summary(user, local_date), "planned_meals": planned,
                "recipes": self.records(user, "recipes")[:50], "saved_foods": self.records(user, "saved-foods")[:50],
                "frequent_foods": self.frequent_foods(user)[:20]}

    def progress(self, user, start_date, end_date):
        span = DateRange(start_date=start_date, end_date=end_date)
        checkins = self.records(user, "check-ins", span.start_date, span.end_date)
        summary = self.summary(user, span.start_date, span.end_date)
        weights = [{"local_date": c["local_date"], "weight_kg": c["measurements"]["weight_kg"]} for c in checkins if "weight_kg" in c["measurements"]]
        measurements = {}
        for field in ("weight_kg", "body_fat_percent", "waist_cm"):
            points = [{"local_date": c["local_date"], "value": c["measurements"][field],
                       **({"source": c["measurements"]["body_fat_source"]} if field == "body_fat_percent" else {})}
                      for c in checkins if field in c["measurements"]]
            measurements[field] = {"points": points, "change": round(points[-1]["value"] - points[0]["value"], 4) if len(points) > 1 else None}
        subjective = {}
        for field in ("hunger", "energy", "recovery", "food_fixation"):
            values = [c["subjective"][field] for c in checkins if field in c["subjective"]]
            subjective[field] = {"count": len(values), "average": round(sum(values) / len(values), 2) if values else None,
                                 "change": values[-1] - values[0] if len(values) > 1 else None}
        adherence = {"below": 0, "within": 0, "above": 0, "unknown": 0}
        for day in summary["days"]:
            target = day["targets"].get("energy_kcal") if day["targets"] else None
            if not day["has_logged_intake"] or not target:
                adherence["unknown"] += 1
            else:
                ratio = day["totals"]["energy_kcal"] / target
                adherence["below" if ratio < .9 else "above" if ratio > 1.1 else "within"] += 1
        return {"profile": self.get(user, "profile"), "checkins": checkins, "latest_weight": weights[-1] if weights else None,
                "measurements": measurements, "subjective_trends": subjective, "nutrition": summary,
                "adherence": {"distribution": adherence, "tolerance_fraction": .1, "note": "Based only on reported intake; logging completeness is unknown."},
                "hydration": self.hydration_summary(user, span.start_date, span.end_date),
                "strategy_at_start": self.current_strategy(user, span.start_date),
                "strategy_history": self.records(user, "nutrition-strategies", span.start_date, span.end_date),
                "behavior_patterns": [p for p in self.records(user, "behavior-patterns") if p["status"] in {"confirmed", "active"}]}

    def lookup_food(self, user, request):
        req = FoodLookupRequest.model_validate(request)
        if not self.provider:
            raise AppError("provider_unavailable", "Nutrition lookup provider is not configured", 503)
        return {"items": [NutritionResult.model_validate(item).data() for item in self.provider.search(req)]}

    def estimate_food(self, user, request):
        req = FoodEstimateRequest.model_validate(request)
        if not self.provider:
            raise AppError("provider_unavailable", "Nutrition estimation provider is not configured", 503)
        result = EstimatedNutrition.model_validate(self.provider.estimate(req))
        if result.source.type != "model_estimate":
            raise AppError("provider_result", "Estimation must identify model provenance", 503)
        for field, known in req.known_nutrition.items():
            if getattr(result.nutrition, field) != known:
                raise AppError("provider_result", "Estimate changed supplied nutrition values", 503)
        return result.data()

    def restaurant_menu(self, user, restaurant_name, location=None, query=None):
        if not restaurant_name or len(restaurant_name) > 200:
            raise AppError("validation", "Provide a restaurant name up to 200 characters")
        if not self.provider:
            raise AppError("provider_unavailable", "Restaurant menu provider is not configured", 503)
        return {"items": [NutritionResult.model_validate(item).data() for item in self.provider.menu(restaurant_name, location, query)]}
