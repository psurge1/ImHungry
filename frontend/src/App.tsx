import { useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, list, localDate } from './api';

const mealOptions = ['breakfast', 'lunch', 'dinner', 'snack', 'other'];
const now = () => new Date().toISOString();
const number = (v: FormData, k: string) => Number(v.get(k));
const value = (v: FormData, k: string) => String(v.get(k) || '').trim();
const lines = (v: FormData, k: string) => value(v, k).split(',').map(s => s.trim()).filter(Boolean);
const pretty = (v: number | undefined) => v === undefined ? '—' : Math.round(v).toLocaleString();
function Field({label, name, type = 'text', defaultValue, required = true, min, max, step}: any) {
  return <label>{label}<input name={name} type={type} defaultValue={defaultValue} required={required} min={min} max={max} step={step ?? (type === 'number' ? 'any' : undefined)} /></label>;
}
function Select({label, name, options, defaultValue}: any) {
  return <label>{label}<select name={name} defaultValue={defaultValue}>{options.map((o: string) => <option key={o} value={o}>{o.replaceAll('_', ' ')}</option>)}</select></label>;
}
function ActionForm({children, submit, label = 'Save', reset = false}: {children: ReactNode; submit: (data: FormData) => Promise<unknown>; label?: string; reset?: boolean}) {
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [saved, setSaved] = useState(false);
  return <form onSubmit={async e => {
    e.preventDefault(); if (busy) return; const form = e.currentTarget;
    setBusy(true); setError(''); setSaved(false);
    try { await submit(new FormData(form)); setSaved(true); if (reset) form.reset(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }}><fieldset disabled={busy}>{children}<button type="submit">{busy ? 'Working…' : label}</button></fieldset>
    {error && <p role="alert" className="error">{error}</p>}{saved && <p role="status" className="success">Done.</p>}
  </form>;
}
function Status({query}: {query: any}) { return query.isPending ? <p role="status">Loading…</p> : query.error ? <p role="alert" className="error">{query.error.message} <button onClick={() => query.refetch()}>Try again</button></p> : null; }
function Macro({data}: {data: any}) { return <div className="macros">{[['energy_kcal', 'Calories'], ['protein_g', 'Protein · g'], ['carbs_g', 'Carbs · g'], ['fat_g', 'Fat · g']].map(([k, label]) => <div key={k}><strong>{pretty(data?.[k])}</strong><small>{label}</small></div>)}</div>; }
function Remove({path, item, refresh}: any) {
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  return <><button className="quiet" disabled={busy} onClick={async () => {
    if (!confirm('Remove this entry?')) return; setBusy(true);
    try { await api(`${path}/${encodeURIComponent(item.entry_ref)}`, {method: 'DELETE', version: item.version}); await refresh(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }}>Remove</button>{error && <p role="alert" className="error">{error}</p>}</>;
}

export default function App({onSignOut}: {onSignOut: () => void}) {
  const [tab, setTab] = useState('Today');
  const qc = useQueryClient();
  const profile = useQuery({queryKey: ['profile'], queryFn: async () => {
    try { return await api('/v1/profile'); } catch (e) { if (e instanceof ApiError && e.status === 404) return null; throw e; }
  }});
  const refresh = () => qc.invalidateQueries();
  return <main><div className="toolbar"><nav aria-label="Main navigation">{['Today', 'Setup', 'Coach', 'Plans', 'Progress'].map(t => <button key={t} aria-current={tab === t ? 'page' : undefined} onClick={() => setTab(t)}>{t}</button>)}</nav><button className="quiet" onClick={onSignOut}>Sign out</button></div>
    <Status query={profile}/>
    {(profile.data === null || profile.data?.configured === false) && tab !== 'Setup' && <p className="notice">Start with <button className="link" onClick={() => setTab('Setup')}>your profile and goals</button> to personalize your coaching.</p>}
    {tab === 'Today' && <Today zone={profile.data?.timezone || 'UTC'} refresh={refresh}/>}
    {tab === 'Setup' && !profile.isPending && !profile.error && <Setup profile={profile.data} refresh={refresh}/>}
    {tab === 'Coach' && <Coach refresh={refresh}/>}
    {tab === 'Plans' && <Plans refresh={refresh}/>}
    {tab === 'Progress' && <Progress refresh={refresh}/>}
    <footer>ImHungry · Nutrition guidance, one day at a time.</footer>
  </main>;
}

function Today({zone, refresh}: any) {
  const [date, setDate] = useState(localDate(zone)), [editing, setEditing] = useState<any>(null), [estimate, setEstimate] = useState<any>(null);
  const summary = useQuery({queryKey: ['summary', date], queryFn: () => api(`/v1/nutrition-summary?start_date=${date}`)});
  const foods = useQuery({queryKey: ['food', date], queryFn: () => list(`/v1/food-log?start_date=${date}&end_date=${date}`)});
  const water = useQuery({queryKey: ['water', date], queryFn: () => list(`/v1/hydration?start_date=${date}&end_date=${date}`)});
  const consumedAt = () => date === localDate(zone) ? now() : new Date(`${date}T12:00:00`).toISOString();
  return <><div className="heading"><div><h1>Your day, at a glance</h1><p>Track what you eat. Make room for what comes next.</p></div><label>Date<input type="date" value={date} onChange={e => {setDate(e.target.value); setEditing(null);}} required /></label></div>
    <section><Status query={summary}/><Macro data={summary.data?.totals}/>{summary.data?.days?.[0]?.targets && <p className="muted">Daily targets: {pretty(summary.data.days[0].targets.energy_kcal)} kcal · {pretty(summary.data.days[0].targets.protein_g)} g protein</p>}<small>Totals reflect logged food only. Day timezone: {zone}.</small></section>
    <div className="columns"><section><h2>{editing ? 'Edit food' : 'Log food'}</h2><p className="muted">Enter nutrition for the whole portion you ate.</p>
      <ActionForm key={editing?.entry_ref || date} label={editing ? 'Save changes' : 'Log food'} reset={!editing} submit={async f => {
        const body = {consumed_at: editing?.consumed_at || consumedAt(), meal_type: value(f, 'meal_type'), food: {display_name: value(f, 'name'), quantity: number(f, 'quantity'), unit: value(f, 'unit'), serving_description: `${value(f, 'quantity')} ${value(f, 'unit')}`}, nutrition: {energy_kcal: number(f, 'calories'), protein_g: number(f, 'protein'), carbs_g: number(f, 'carbs'), fat_g: number(f, 'fat')}, source: {type: 'user_provided'}, ...(editing ? {estimate: null} : {})};
        await api('/v1/food-log' + (editing ? `/${encodeURIComponent(editing.entry_ref)}` : ''), {method: editing ? 'PATCH' : 'POST', body, version: editing?.version}); setEditing(null); await refresh();
      }}><Field label="Food" name="name" defaultValue={editing?.food.display_name}/><div className="fields"><Field label="Quantity" name="quantity" type="number" min="0.01" defaultValue={editing?.food.quantity || 1}/><Field label="Unit" name="unit" defaultValue={editing?.food.unit || 'serving'}/><Select label="Meal" name="meal_type" options={mealOptions} defaultValue={editing?.meal_type || 'other'}/></div><div className="fields">{[['calories', 'Calories', 'energy_kcal'], ['protein', 'Protein (g)', 'protein_g'], ['carbs', 'Carbs (g)', 'carbs_g'], ['fat', 'Fat (g)', 'fat_g']].map(([name, label, k]) => <Field key={name} name={name} label={label} type="number" min="0" defaultValue={editing?.nutrition[k]}/>)}</div></ActionForm>
      {editing && <button className="quiet" onClick={() => setEditing(null)}>Cancel editing</button>}
      <details><summary>Need a nutrition estimate?</summary><ActionForm label="Estimate" submit={async f => setEstimate(await api('/v1/foods/estimate', {method: 'POST', body: {description: value(f, 'description'), quantity: number(f, 'quantity'), unit: value(f, 'unit')}}))}><Field label="Describe the food and preparation" name="description"/><div className="fields"><Field label="Quantity" name="quantity" type="number" min="0.01" defaultValue={1}/><Field label="Unit" name="unit" defaultValue="serving"/></div></ActionForm>
      {estimate && <div className="notice"><strong>{estimate.food.display_name} · estimate</strong><Macro data={estimate.nutrition}/><p>{estimate.estimate?.assumptions?.join(' ')}</p><ActionForm label="Log this estimate" submit={async () => {await api('/v1/food-log', {method: 'POST', body: {...estimate, consumed_at: consumedAt(), meal_type: 'other'}}); setEstimate(null); await refresh();}}><span/></ActionForm></div>}</details>
    </section><section><h2>Food log</h2><Status query={foods}/>{foods.data?.length === 0 && <p className="empty">No food logged for this day.</p>}{foods.data?.map(f => <article key={f.entry_ref}><div><strong>{f.food.display_name}</strong><p>{f.food.quantity} {f.food.unit} · {pretty(f.nutrition.energy_kcal)} kcal · {pretty(f.nutrition.protein_g)} g protein{f.estimate ? ' · estimated' : ''}</p></div><div className="actions"><button className="quiet" onClick={() => setEditing(f)}>Edit</button><Remove path="/v1/food-log" item={f} refresh={refresh}/></div></article>)}</section></div>
    <section><h2>Hydration</h2><Status query={water}/><p>{pretty(water.data?.reduce((n, r) => n + r.amount_ml, 0))} ml logged</p><ActionForm label="Add drink" reset submit={async f => {await api('/v1/hydration', {method: 'POST', body: {consumed_at: consumedAt(), amount_ml: number(f, 'amount'), beverage_name: value(f, 'beverage')}}); await refresh();}}><div className="fields"><Field label="Amount (ml)" name="amount" type="number" min="1" max="10000" defaultValue={250}/><Field label="Drink" name="beverage" defaultValue="water"/></div></ActionForm>{water.data?.map(w => <article key={w.entry_ref}><span>{w.beverage_name} · {w.amount_ml} ml</span><Remove path="/v1/hydration" item={w} refresh={refresh}/></article>)}</section>
  </>;
}

function Setup({profile, refresh}: any) {
  const [calculated, setCalculated] = useState<any>(null);
  const strategy = useQuery({queryKey: ['strategy'], queryFn: () => api('/v1/nutrition-strategies/current')});
  return <><h1>Your starting point</h1><p>Save your profile first, then calculate and accept your targets.</p><div className="columns"><section><h2>Profile</h2>
    <ActionForm key={profile?.version || 0} label="Save profile" submit={async f => {
      const body: any = {timezone: value(f, 'timezone'), unit_system: 'metric', dietary_preferences: lines(f, 'preferences'), dietary_restrictions: lines(f, 'restrictions'), allergies: lines(f, 'allergies'), disliked_foods: lines(f, 'disliked')};
      if (value(f, 'height')) body.height_cm = number(f, 'height');
      if (value(f, 'dob')) body.date_of_birth = value(f, 'dob');
      if (value(f, 'sex')) body.sex_for_bmr_equation = value(f, 'sex');
      if (value(f, 'activity')) body.activity_context = {...profile?.activity_context, level: value(f, 'activity')};
      await api('/v1/profile', {method: 'PATCH', version: profile?.version || 0, body}); setCalculated(null); await refresh();
    }}><Field label="Timezone" name="timezone" defaultValue={profile?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone}/><div className="fields"><Field label="Height (cm)" name="height" type="number" min="51" max="250" required={false} defaultValue={profile?.height_cm}/><Field label="Date of birth" name="dob" type="date" required={false} defaultValue={profile?.date_of_birth}/></div><div className="fields"><Select label="Sex used for BMR calculation" name="sex" options={['', 'male', 'female']} defaultValue={profile?.sex_for_bmr_equation || ''}/><Select label="Activity level" name="activity" options={['', 'sedentary', 'lightly_active', 'moderately_active', 'very_active', 'extra_active']} defaultValue={profile?.activity_context?.level || ''}/></div>{[['preferences', 'Dietary preferences', 'dietary_preferences'], ['restrictions', 'Dietary restrictions', 'dietary_restrictions'], ['allergies', 'Allergies', 'allergies'], ['disliked', 'Foods you dislike', 'disliked_foods']].map(([name, label, k]) => <Field key={name} name={name} label={`${label} (comma-separated)`} required={false} defaultValue={profile?.[k]?.join(', ')}/>)}</ActionForm>
    </section><section><h2>Nutrition goals</h2><Status query={strategy}/>{strategy.data?.strategy && <><p>Current targets</p><Macro data={strategy.data.strategy.targets}/></>}
    <ActionForm label="Calculate targets" submit={async f => {const type = value(f, 'type'); const result = await api('/v1/nutrition-strategies/calculate', {method: 'POST', body: {goal: {type, baseline_weight_kg: number(f, 'baseline'), goal_weight_kg: type === 'maintain_weight' ? number(f, 'baseline') : number(f, 'goal'), desired_rate_kg_per_week: type === 'maintain_weight' ? 0 : number(f, 'rate')}}}); setCalculated(result);}}>
      <Select label="Goal" name="type" options={['maintain_weight', 'lose_weight']}/><Field label="Starting weight (kg)" name="baseline" type="number" min="21" max="500"/><Field label="Goal weight (kg, for weight loss)" name="goal" type="number" min="21" max="500" required={false}/><Field label="Desired loss (kg/week, for weight loss)" name="rate" type="number" min="0" max="1" defaultValue={0.25}/>
    </ActionForm>{calculated && (calculated.complete ? <div className="notice"><h3>Proposed targets</h3><Macro data={calculated.targets}/><p>{calculated.calculation.assumptions?.join(' ')}</p><ActionForm label="Accept these targets" submit={async () => {const {goal, targets, calculation} = calculated; await api('/v1/nutrition-strategies', {method: 'POST', body: {goal, targets, calculation, effective_from: now(), change_reason: 'Accepted targets in frontend'}}); setCalculated(null); await refresh();}}><span/></ActionForm></div> : <p role="alert" className="notice">Complete the missing profile information and save it first: {calculated.missing_inputs?.join(', ')}.</p>)}</section></div></>;
}

function Coach({refresh}: any) {
  const [selected, setSelected] = useState(''), [draft, setDraft] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [pending, setPending] = useState<{id: string; message: string; conversation: string} | null>(null);
  const [sent, setSent] = useState('');
  const conversations = useQuery({queryKey: ['conversations'], queryFn: () => list('/v1/conversations')});
  const messages = useQuery({queryKey: ['messages', selected], queryFn: () => api(`/v1/conversations/${selected}/messages`), enabled: !!selected});
  async function send() {
    if (busy || (!pending && !draft.trim())) return; setBusy(true); setError('');
    try {
      let id = selected;
      if (!id) { const c = await api('/v1/conversations', {method: 'POST', body: {title: draft.slice(0, 100) || 'Nutrition conversation'}}); id = c.conversation_id; setSelected(id); }
      const attempt = pending || {id: crypto.randomUUID(), message: draft.trim(), conversation: id};
      setPending(attempt); setSent(attempt.message);
      await api(`/v1/conversations/${attempt.conversation}/messages`, {method: 'POST', key: attempt.id, body: {message: attempt.message, client_request_id: attempt.id}});
      setPending(null); setDraft(''); setSent(''); await refresh();
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  return <><h1>A little help with food</h1><p>Ask for meal ideas, recipes, restaurant options, or coaching based on your logs.</p><section>
    <div className="toolbar"><label>Conversation<select disabled={busy || !!pending} value={selected} onChange={e => {setSelected(e.target.value); setError(''); setSent('');}}><option value="">New conversation</option>{conversations.data?.filter(c => c.status === 'active').map(c => <option key={c.conversation_id} value={c.conversation_id}>{c.title}</option>)}</select></label><button className="quiet" disabled={busy} onClick={() => {setSelected(''); setPending(null); setSent(''); setError(''); setDraft('');}}>New conversation</button></div>
    <Status query={conversations}/>{selected && <Status query={messages}/>}
    <div className="messages" aria-live="polite">{!selected && <p className="empty">Try “Help me plan dinner” or “How can I handle late-night hunger?”<br/>Ask me to save a recipe, log a meal, or plan for a restaurant visit.</p>}{messages.data?.messages?.map((m: any, i: number) => <div className={`message ${m.role}`} key={i}><small>{m.role === 'user' ? 'You' : 'ImHungry'}</small><p>{m.text}</p></div>)}{sent && <div className="message user"><small>You · {busy ? 'sending' : 'not yet confirmed'}</small><p>{sent}</p></div>}{busy && <p role="status">Thinking and checking your context. This may take a minute…</p>}</div>
    <form onSubmit={e => {e.preventDefault(); void send();}}><label>Your message<textarea maxLength={12000} rows={3} value={draft} disabled={busy || !!pending} onChange={e => setDraft(e.target.value)} placeholder="What would you like help with?"/></label><button disabled={busy || (!pending && !draft.trim())}>{busy ? 'Working…' : pending ? 'Retry same message' : 'Send message'}</button></form>
    {error && <p role="alert" className="error">{error} {pending && 'Retry keeps the same request ID to avoid duplicate writes. If the conversation is blocked, start a new one; the failed conversation needs operator recovery.'}</p>}
  </section></>;
}

function Plans({refresh}: any) {
  const meals = useQuery({queryKey: ['plans'], queryFn: () => list('/v1/planned-meals')});
  const recipes = useQuery({queryKey: ['recipes'], queryFn: () => list('/v1/recipes')});
  const saved = useQuery({queryKey: ['saved'], queryFn: () => list('/v1/saved-foods')});
  return <><h1>Meals worth looking forward to</h1><p>Ask your coach for ideas and tell it which plans or recipes you want to save.</p><div className="columns"><section><h2>Plan a meal</h2><ActionForm label="Save meal plan" reset submit={async f => {await api('/v1/planned-meals', {method: 'POST', body: {scheduled_at: new Date(value(f, 'time')).toISOString(), meal_slot: value(f, 'meal'), items: [{name: value(f, 'name'), serving_description: value(f, 'portion')}]}}); await refresh();}}><Field label="Meal" name="name"/><Field label="Portion" name="portion"/><Field label="When (your device timezone)" name="time" type="datetime-local"/><Select label="Meal slot" name="meal" options={mealOptions}/></ActionForm></section><section><h2>Saved plans</h2><Status query={meals}/>{meals.data?.length === 0 && <p className="empty">No plans yet.</p>}{meals.data?.map(m => <article key={m.entry_ref}><div><strong>{m.items.map((i: any) => i.name).join(', ')}</strong><p>{new Date(m.scheduled_at).toLocaleString()} · {m.status}</p>{m.status === 'planned' && <ActionForm label="Update status" submit={async f => {await api(`/v1/planned-meals/${encodeURIComponent(m.entry_ref)}`, {method: 'PATCH', version: m.version, body: {status: value(f, 'status')}}); await refresh();}}><Select label="Status" name="status" options={['completed', 'skipped']}/></ActionForm>}<small>Completing a plan does not log food.</small></div><Remove path="/v1/planned-meals" item={m} refresh={refresh}/></article>)}</section></div><div className="columns"><section><h2>Recipes</h2><Status query={recipes}/>{recipes.data?.length === 0 && <p className="empty">Ask your coach to create and save a recipe.</p>}{recipes.data?.map(r => <article key={r.entry_ref}><div><strong>{r.name}</strong><p>{r.yield?.servings} servings</p><Macro data={r.nutrition_per_serving}/></div><Remove path="/v1/recipes" item={r} refresh={refresh}/></article>)}</section><section><h2>Saved foods</h2><Status query={saved}/>{saved.data?.length === 0 && <p className="empty">Ask your coach to save foods you eat often.</p>}{saved.data?.map(s => <article key={s.entry_ref}><div><strong>{s.name}</strong><p>{s.default_serving.quantity} {s.default_serving.unit}</p><Macro data={s.nutrition_per_serving}/></div><Remove path="/v1/saved-foods" item={s} refresh={refresh}/></article>)}</section></div></>;
}

function Progress({refresh}: any) {
  const entries = useQuery({queryKey: ['checkins'], queryFn: () => list('/v1/check-ins')});
  const patterns = useQuery({queryKey: ['patterns'], queryFn: () => list('/v1/behavior-patterns')});
  return <><h1>Check in with yourself</h1><p>Notice patterns over time. A single day does not tell the whole story.</p><div className="columns"><section><h2>New check-in</h2><ActionForm label="Save check-in" reset submit={async f => {
    const measurements: any = {}, subjective: any = {};
    if (value(f, 'weight')) measurements.weight_kg = number(f, 'weight');
    for (const k of ['hunger', 'energy', 'recovery', 'food_fixation']) if (value(f, k)) subjective[k] = number(f, k);
    await api('/v1/check-ins', {method: 'POST', body: {recorded_at: now(), measurements, subjective, ...(value(f, 'notes') ? {notes: value(f, 'notes')} : {})}}); await refresh();
  }}><Field label="Weight (kg, optional)" name="weight" type="number" min="21" max="500" required={false}/><div className="fields">{['hunger', 'energy', 'recovery', 'food_fixation'].map(k => <Field key={k} label={`${k.replaceAll('_', ' ')} (1–10)`} name={k} type="number" min="1" max="10" step="1" required={false}/>)}</div><label>Notes<textarea name="notes" rows={3} maxLength={2000}/></label></ActionForm></section><section><h2>Your check-ins</h2><Status query={entries}/>{entries.data?.length === 0 && <p className="empty">No check-ins yet.</p>}{entries.data?.map(c => <article key={c.entry_ref}><div><strong>{new Date(c.recorded_at).toLocaleDateString()}</strong>{c.measurements.weight_kg && <p>{c.measurements.weight_kg} kg</p>}<p>{Object.entries(c.subjective).filter(([, v]) => typeof v === 'number').map(([k, v]) => `${k.replaceAll('_', ' ')} ${v}/10`).join(' · ')}</p><p>{c.notes}</p></div><Remove path="/v1/check-ins" item={c} refresh={refresh}/></article>)}</section></div><section><h2>Patterns you’ve confirmed</h2><Status query={patterns}/>{patterns.data?.length === 0 && <p className="empty">Talk with your coach about recurring habits. Patterns are saved after your confirmation.</p>}{patterns.data?.map(p => <article key={p.entry_ref}><div><strong>{p.description}</strong><p>{p.strategies?.map((s: any) => s.description).join(' ')}</p></div><small>{p.status}</small></article>)}</section></>;
}
