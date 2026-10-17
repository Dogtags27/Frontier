const FIELDS: Record<string, string> = {
  "cs.ai": "Artificial Intelligence",
  "cs.ar": "Hardware Architecture",
  "cs.cc": "Computational Complexity",
  "cs.ce": "Computational Engineering",
  "cs.cg": "Computational Geometry",
  "cs.cl": "Natural Language Processing",
  "cs.cr": "Cryptography and Security",
  "cs.cv": "Computer Vision",
  "cs.cy": "Computers and Society",
  "cs.db": "Databases",
  "cs.dc": "Distributed and Parallel Computing",
  "cs.dl": "Digital Libraries",
  "cs.dm": "Discrete Mathematics",
  "cs.ds": "Data Structures and Algorithms",
  "cs.et": "Emerging Technologies",
  "cs.fl": "Formal Languages and Automata",
  "cs.gl": "General Literature",
  "cs.gr": "Graphics",
  "cs.gt": "Game Theory",
  "cs.hc": "Human-Computer Interaction",
  "cs.ir": "Information Retrieval",
  "cs.it": "Information Theory",
  "cs.lg": "Machine Learning",
  "cs.lo": "Logic in Computer Science",
  "cs.ma": "Multiagent Systems",
  "cs.mm": "Multimedia",
  "cs.ms": "Mathematical Software",
  "cs.na": "Numerical Analysis",
  "cs.ne": "Neural and Evolutionary Computing",
  "cs.ni": "Networking and Internet Architecture",
  "cs.oh": "Other Computer Science",
  "cs.os": "Operating Systems",
  "cs.pf": "Performance",
  "cs.pl": "Programming Languages",
  "cs.ro": "Robotics",
  "cs.sc": "Symbolic Computation",
  "cs.sd": "Sound",
  "cs.se": "Software Engineering",
  "cs.si": "Social and Information Networks",
  "cs.sy": "Systems and Control",
  "stat.ml": "Statistical Machine Learning",
  "stat.me": "Statistical Methodology",
  "stat.th": "Statistics Theory",
  "stat.ap": "Applied Statistics",
  "stat.co": "Statistical Computation",
  "math.oc": "Optimization and Control",
  "math.st": "Statistics Theory",
  "math.pr": "Probability",
  "math.co": "Combinatorics",
  "math.na": "Numerical Analysis",
  "math.it": "Information Theory",
  "eess.as": "Audio and Speech Processing",
  "eess.iv": "Image and Video Processing",
  "eess.sp": "Signal Processing",
  "eess.sy": "Systems and Control",
  "q-bio.nc": "Neurons and Cognition",
  "q-bio.qm": "Quantitative Methods",
  "physics.comp-ph": "Computational Physics",
  "quant-ph": "Quantum Physics",
};

const CODE = /\b([a-z]{2,7}(?:-[a-z]+)?\.[a-z]{2,7})\b/i;

function one(code: string): string {
  const key = code.trim().toLowerCase();
  if (!key) return "";
  if (FIELDS[key]) return FIELDS[key];
  const dotted = key.startsWith("cs.") ? key : `cs.${key}`;
  if (FIELDS[dotted]) return FIELDS[dotted];
  if (key.startsWith("cs.")) return "Computer Science";
  return code.trim();
}

export function fieldName(code?: string | null): string {
  if (!code) return "";
  const raw = code.trim();
  if (!raw) return "";
  const parts = raw.split(/[,;/|]+/).map((part) => part.trim()).filter(Boolean);
  if (parts.length > 1) {
    const names = [...new Set(parts.map(one).filter(Boolean))];
    return names.join(" · ");
  }
  const match = raw.match(CODE);
  if (match) return one(match[1]);
  return one(raw);
}
