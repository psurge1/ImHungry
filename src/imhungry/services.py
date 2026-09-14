"""Shared application behavior. HTTP and Strands call this layer independently."""

import base64
import hashlib
import json
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from .errors import AppError, Conflict, NotFound
from .models import RECORDS, DateRange, Nutrition, StrategyCalculationRequest
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
        hidden = {"PK", "SK", "GSI1PK", "GSI1SK", "invocation_id", "invocation_status", "pending_request"}
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
        days = []
        for offset in range((span.end_date - span.start_date).days + 1):
            day = span.start_date + timedelta(days=offset)
            foods = [e for e in entries if e["local_date"] == day.isoformat()]
            total = total_nutrition([e["nutrition"] for e in foods])
            strategy = self.current_strategy(user, day)
            targets = strategy["targets"] if strategy else None
            days.append({"local_date": str(day), "totals": total, "entry_count": len(foods), "has_logged_intake": bool(foods),
                         "targets": targets, "remaining": {k: round(v - total[k], 4) for k, v in targets.items() if k in total} if targets else None})
        total = total_nutrition([e["nutrition"] for e in entries])
        return {"days": days, "totals": total, "averages_per_calendar_day": {k: round(v / len(days), 4) for k, v in total.items()},
                "logged_days": sum(d["has_logged_intake"] for d in days),
                "note": "Totals describe logged intake only; an unlogged day does not imply zero consumption."}
