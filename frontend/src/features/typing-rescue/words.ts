/**
 * IELTS / academic vocabulary for Typing Rescue, stratified by length so the
 * wave system can start easy (short words) and grow harder (longer words).
 * Real words, lowercase, letters only.
 */

/** 3–4 letters — wave 1 material. */
export const SHORT_WORDS: readonly string[] = [
  "aid", "bias", "cite", "cope", "core", "data", "deny", "emit", "fund", "gap",
  "gene", "halt", "hub", "levy", "link", "mere", "mode", "myth", "node", "norm",
  "odds", "opt", "pact", "peak", "peer", "pose", "rate", "rely", "rife", "risk",
  "role", "rule", "sole", "span", "stem", "swap", "task", "tend", "term", "text",
  "tier", "tone", "urge", "vary", "vast", "veto", "void", "ward", "wary", "zone",
];

/** 5–7 letters — introduced from wave 2. */
export const MEDIUM_WORDS: readonly string[] = [
  "adapt", "adopt", "brief", "cease", "civil", "claim", "defer", "draft", "equip",
  "evoke", "exert", "forge", "grant", "imply", "index", "infer", "merit", "motive",
  "notion", "occur", "offset", "prone", "quota", "range", "ratio", "react", "scope",
  "shift", "solid", "spark", "stark", "steer", "theme", "trace", "trend", "urban",
  "valid", "yield", "acquire", "analyse", "benefit", "capable", "clarify", "complex",
  "concept", "conduct", "consent", "context", "convert", "declare", "deduce", "define",
  "deploy", "derive", "detect", "devote", "diverse", "dynamic", "enhance", "ensure",
  "exceed", "exhibit", "exploit", "expose", "impose", "induce", "inspect", "justify",
  "monitor", "mutual", "neutral", "obtain", "occupy", "pursue", "refine", "reveal",
  "revise", "sustain",
];

/** 8+ letters — the deep end, from wave 3 on. */
export const LONG_WORDS: readonly string[] = [
  "abstract", "academic", "allocate", "ambiguous", "anticipate", "apparent",
  "arbitrary", "assemble", "attribute", "authentic", "coherent", "coincide",
  "collapse", "commence", "comprise", "conceive", "conclude", "constrain",
  "cumulative", "dedicate", "demonstrate", "diminish", "distribute", "dominate",
  "eliminate", "emphasis", "encounter", "enormous", "equivalent", "establish",
  "estimate", "evaluate", "eventual", "evidence", "evolution", "explicit",
  "extensive", "facilitate", "feasible", "fluctuate", "formulate", "framework",
  "function", "fundamental", "generate", "guarantee", "hierarchy", "hypothesis",
  "identical", "ideology", "illustrate", "implement", "incentive", "incorporate",
  "indicate", "inevitable", "innovate", "integrate", "integrity", "interpret",
  "intrinsic", "magnitude", "mechanism", "negotiate", "objective", "paradigm",
  "parallel", "parameter", "perceive", "persistent", "perspective", "phenomenon",
  "plausible", "potential", "precedent", "predominant", "preliminary", "principle",
  "procedure", "prohibit", "prominent", "proportion", "qualitative", "rational",
  "reinforce", "relevant", "reluctant", "resource", "restrain", "restrict",
  "scenario", "sequence", "significant", "simulate", "sophisticated", "strategy",
  "subsequent", "substitute", "sufficient", "supplement", "suppress", "tangible",
  "technique", "temporary", "threshold", "transform", "transparent", "ultimate",
  "underlying", "variable", "voluntary", "widespread",
];
