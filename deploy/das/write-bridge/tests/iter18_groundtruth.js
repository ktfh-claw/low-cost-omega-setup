// Iteration-18 ground truth: issue-2 Phase-0 mongo inspection (db "das").
// P0a: confirm link docs are keyed _id = handle and carry the v4-shaped
//      custom_attributes (metta_expression, provenance_ref,
//      provenance_git_commit, provenance_blob_sha256) on the TOP link doc
//      written by iter18_probe_mongo_attrs.py (write mode).
// P0b: attribute-overwrite semantics after the SECOND write (same
//      deterministic handles, PROV_B payload): the doc's custom_attributes
//      show exactly one provenance_ref value (OVERWRITE, expected per
//      add_atoms re-put) or multiple (MERGE/APPEND).
// Handles are the deterministic PHASE5_HANDLES output of the probe run;
// symbol nodes checked BY NAME (never by guessed handles).
// Run: docker exec omega-das-integration-mongodb-1 mongosh \
//   --username "$MONGODB_USERNAME" --password "$MONGODB_PASSWORD" \
//   --authenticationDatabase admin --quiet /tmp/iter18_groundtruth.js
const topLink = "53db949169a33d28dbb84f07df4fdcf8";
const linkIds = ["53db949169a33d28dbb84f07df4fdcf8"].concat(["9f71f321011e61f0aa91380e803df730", "dacff949948908e54b81f84021dbaf79"]);
const nodeIds = ["8863f97f51763a229a97249ef97fad98", "a1a0178a856abbf59d49d16b6eeb10d3"];
db = db.getSiblingDB("das");
const topDoc = db.links.findOne({ _id: topLink });
print("topLinkExists: " + (topDoc !== null));
print("topLinkType: " + (topDoc ? topDoc.type : "N/A"));
print("topLinkTargets: " + (topDoc ? JSON.stringify(topDoc.targets) : "N/A"));
print("topLinkCustomAttributes: " + (topDoc ? JSON.stringify(topDoc.custom_attributes) : "N/A"));
if (topDoc && topDoc.custom_attributes) {
  const attrs = topDoc.custom_attributes;
  print("provRefCount: " + (attrs.provenance_ref ? 1 : 0));
  print("provRefValue: " + (attrs.provenance_ref || "MISSING"));
  print("provCommitValue: " + (attrs.provenance_git_commit || "MISSING"));
  print("provSha256Value: " + (attrs.provenance_blob_sha256 || "MISSING"));
  print("mettaExpression: " + (attrs.metta_expression || "MISSING"));
}
const otherLinks = linkIds.filter(function (id) { return id !== topLink; });
print("subLinksFound: " + db.links.countDocuments({ _id: { $in: otherLinks } }));
// Sub-links and nodes must NOT carry provenance attributes (decoration is
// top-link only). Report any that do.
const attrCarriers = db.links.find({
  _id: { $in: linkIds },
  "custom_attributes.provenance_ref": { $exists: true }
}).toArray();
print("docsWithProvRef: " + JSON.stringify(attrCarriers.map(function (d) { return d._id; })));
print("uniqueNodesFound: " + db.nodes.countDocuments({ _id: { $in: nodeIds } }));
print("canarySymbolNode: " + db.nodes.countDocuments({ name: '"omega-bridge-canary-20261027-iter18"' }));
print("linksTotal: " + db.links.countDocuments({}));
print("nodesTotal: " + db.nodes.countDocuments({}));
