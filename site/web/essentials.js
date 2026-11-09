/* Explained: the essential clips, by category, in learning order. A hand-picked few of the full set in
   ../data/explainers.js (ids from there); their quotes are in ../data/quotes.js (scripts/build_quotes.py).
   Used by explained.html and by each episode's "From this episode" block on index.html. */
window.FFW_ESSENTIALS = [
  { id: "fund", title: "The Fundamentals",
    ids: ["2-566", "1-1289", "5-2987", "1-638", "15-1123"] },
  { id: "skull", title: "The Skull",
    ids: ["16-2230", "16-2279", "14-556", "14-2283", "14-648", "2-1394", "22-2278", "22-509", "19-874"] },
  { id: "params", title: "The Parameters",
    ids: ["2-692", "11-133", "12-2946", "19-2095", "16-2996"] },
  { id: "mech", title: "The Mechanism",
    ids: ["3-4229", "19-1852"] },
  { id: "conf", title: "Confounds and Target Engagement",
    ids: ["1-232", "20-876", "19-2356", "2-1107"] },
  { id: "safe", title: "Safety",
    ids: ["4-242", "14-1987", "4-52"] },
];
// The chapters above, in page order, each with no (1, 2, …) and clips: its explainers.js entries ({id, n, s, e, title,
// who, level, terms, …}) in the order of ids; an id explainers.js lacks is left out. The quotes are in ../data/quotes.js.
window.FFW_CLIPS = function () {
  const all = new Map(((window.FF_EXPLAIN || {}).explainers || []).map(x => [x.id, x]));
  return window.FFW_ESSENTIALS.map((c, i) => ({ ...c, no: i + 1, clips: c.ids.map(id => all.get(id)).filter(Boolean) }));
};
