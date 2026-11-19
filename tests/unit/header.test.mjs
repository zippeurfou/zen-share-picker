import test from "node:test";
import assert from "node:assert/strict";
import { headerText } from "../../src/lib/header.mjs";

test("no_site_reads_choose_what_to_share", () => {
  assert.equal(headerText(null), "Choose what to share");
});

test("name_only", () => {
  assert.equal(
    headerText({ name: "meet.test", secondName: null }),
    "meet.test wants to see your screen"
  );
});

test("name_and_second_name", () => {
  assert.equal(
    headerText({ name: "meet.test", secondName: "embed.test" }),
    "meet.test wants to give embed.test permission to see your screen"
  );
});

test("no_name_is_a_local_file", () => {
  assert.equal(
    headerText({ name: null, secondName: null }),
    "This local file wants to see your screen"
  );
  assert.equal(
    headerText({ name: null, secondName: "embed.test" }),
    "This local file wants to see your screen"
  );
});

test("non_string_or_empty_names_count_as_absent", () => {
  for (const bad of [undefined, "", 0, 42, {}, [], true]) {
    assert.equal(
      headerText({ name: bad, secondName: null }),
      "This local file wants to see your screen"
    );
    assert.equal(
      headerText({ name: "meet.test", secondName: bad }),
      "meet.test wants to see your screen"
    );
  }
  assert.equal(headerText({}), "This local file wants to see your screen");
});
