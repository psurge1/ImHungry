type Activity = {name: string; status: string};
const labels: Record<string, string> = {
  lookup_restaurant_menu: 'Look up restaurant menu',
  estimate_food_nutrition: 'Estimate food nutrition',
  lookup_food_nutrition: 'Look up food nutrition',
};
const statuses: Record<string, string> = {
  completed: 'Completed', failed: 'Failed', unavailable: 'No data available', unconfirmed: 'Result not confirmed',
};
export default function ToolActivity({items}: {items?: Activity[]}) {
  if (!items?.length) return null;
  return <details className="tool-activity" open><summary>Tool activity · {items.length}</summary>
    <ul>{items.map((item, index) => <li key={index}><span>{labels[item.name] || item.name.replaceAll('_', ' ')}</span><strong>{statuses[item.status] || statuses.unconfirmed}</strong></li>)}</ul>
  </details>;
}
