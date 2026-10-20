// Iteration-16 ground truth: canary residue check in the live DAS mongo (db "das").
// Handles from PHASE6_HANDLES of the iter-16 (Phase-4 close-out) probe; symbol
// nodes checked BY NAME (never by guessed handles); E1 canary = the
// 2026-10-18 broker-write campaign fact, handle 7d37146a90a4063c28ec72204879835f.
const linkIds = ["9c42e9dbe45d7d79d936b9cacba412eb", "aa2153959776b0f08ecacd7396be8085", "46c7b670cb5a6cb3fc7d17d7730bcb3a"];
const nodeIds = ["9677d6b54116b95a585405fef6a6280e", "fbb7253bd84699cfd1e93226e891b443"];
db = db.getSiblingDB("das");
print("canaryLinks: " + db.links.countDocuments({ _id: { $in: linkIds } }));
print("uniqueNodes: " + db.nodes.countDocuments({ _id: { $in: nodeIds } }));
print("symbolInheritance: " + db.nodes.countDocuments({ name: "Inheritance" }));
print("symbolConcept: " + db.nodes.countDocuments({ name: "Concept" }));
print("e1CanaryLink: " + db.links.countDocuments({ _id: "7d37146a90a4063c28ec72204879835f" }));
print("nodesTotal: " + db.nodes.countDocuments({}));
print("linksTotal: " + db.links.countDocuments({}));
