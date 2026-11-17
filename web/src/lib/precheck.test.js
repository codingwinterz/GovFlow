import { test } from "node:test";
import assert from "node:assert/strict";
import {
  PRECHECK_DISCLAIMER,
  filterUploadableDocs,
  normalizePrecheckOptions,
  precheckBody,
  precheckError,
  precheckView,
  validatePrecheckFile,
} from "./precheck.js";

test("filterUploadableDocs excludes application and keeps citizen documents", () => {
  const docs = [
    { id: "application", label: "Application form" },
    { id: "ownership_record", label: "Ownership record (Form I & XIV)" },
    { id: "identity_proof", label: "Identity proof" },
  ];
  assert.deepEqual(filterUploadableDocs(docs), [
    { id: "ownership_record", label: "Ownership record (Form I & XIV)" },
    { id: "identity_proof", label: "Identity proof" },
  ]);
});

test("normalizePrecheckOptions handles API payload and empty array fallback", () => {
  const empty = normalizePrecheckOptions([]);
  assert.deepEqual(empty.schemes, []);
  assert.equal(empty.disclaimer, PRECHECK_DISCLAIMER);

  const parsed = normalizePrecheckOptions({
    schemes: [
      {
        scheme: "land_acquisition",
        title: "Land acquisition",
        documents: [
          { id: "application", label: "Application form" },
          { id: "mutation_record", label: "Mutation record" },
        ],
      },
    ],
  });
  assert.equal(parsed.schemes.length, 1);
  assert.deepEqual(parsed.schemes[0].documents, [{ id: "mutation_record", label: "Mutation record" }]);
  assert.throws(() => normalizePrecheckOptions({ detail: "unexpected" }), /Invalid precheck options/);
});

test("validatePrecheckFile checks extension and size", () => {
  assert.match(validatePrecheckFile(null), /Choose a document/);
  assert.match(validatePrecheckFile({ name: "malware.exe", size: 100 }), /Unsupported file type/);
  assert.match(validatePrecheckFile({ name: "scan.png", size: 11 * 1024 * 1024 }), /too large/);
  assert.equal(validatePrecheckFile({ name: "scan.png", size: 1024 }), null);
  assert.equal(validatePrecheckFile({ name: "doc.PDF", size: 2048 }), null);
});

test("precheckBody and precheckView format plain-language feedback without snake_case", () => {
  assert.deepEqual(
    precheckBody(" land_acquisition ", " mutation_record ", " doc.txt ", "YWJj"),
    { scheme: "land_acquisition", document_type: "mutation_record", filename: "doc.txt", content_base64: "YWJj" },
  );
  const view = precheckView({
    scheme_label: "Land acquisition",
    document_label: "Ownership record (Form I & XIV)",
    readable: "partly",
    fields: [
      { label: "Name", status: "found", what_we_read: "Ramesh Naik" },
      { label: "Survey number", status: "could not read", what_we_read: null },
    ],
    issues: ["Could not read clearly: Survey number."],
    next_steps: ["Bring a clearer copy or the original Ownership record (Form I & XIV)."],
    used_fallback: true,
    disclaimer: PRECHECK_DISCLAIMER,
  });
  assert.equal(view.readable, "partly");
  assert.match(view.readableText, /Partly/);
  assert.equal(view.usedFallback, true);
  assert.equal(view.fields[0].whatWeRead, "Ramesh Naik");
  assert.equal(view.fields[1].whatWeRead, null);
});

test("precheckError explains rate limits and file errors plainly", () => {
  assert.match(precheckError(429), /Too many document checks/);
  assert.match(precheckError(413), /too large/);
  assert.equal(precheckError(400, "The file content is not a .png file."), "The file content is not a .png file.");
  assert.match(precheckError(500), /Could not check the document/);
});
