// Which gaps survive the layout parser the take page actually uses.
//
// Not an approximation of that grammar -- the grammar itself. A template is
// not plain text with {{N}} in it: a line starting with "+" is a table row, ">"
// is a flow-chart step, "#" a heading, and "|" splits a label from its value.
// Book prose collides with all of them, and when it does the gap does not
// render and the paper silently comes up a question short.
//
//   node --experimental-strip-types seed/check_template.mjs <<< "<template>"
//
// Prints the gap numbers that survive, one per line.
import { parseTemplateLayout } from "../frontend/src/features/paper/form-syntax.ts";

const template = await new Promise((resolve) => {
  let buf = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (d) => (buf += d));
  process.stdin.on("end", () => resolve(buf));
});

const seen = new Set();
for (const m of JSON.stringify(parseTemplateLayout(template)).matchAll(/"number":(\d+)/g)) {
  seen.add(Number(m[1]));
}
console.log([...seen].sort((a, b) => a - b).join("\n"));
