import test from "node:test";
import assert from "node:assert/strict";
import { zenWindowIds } from "../../src/glue/windows.sys.mjs";

// A fake Services whose window enumerator yields `wins`; each is a window
// whose windowUtils.webrtcRawDeviceId is the value, or throws for "throw".
function services(wins) {
  const calls = [];
  return {
    calls,
    wm: {
      getEnumerator(type) {
        calls.push(type);
        return wins.map(id => ({
          get windowUtils() {
            return {
              get webrtcRawDeviceId() {
                if (id === "throw") {
                  throw new Error("no device id");
                }
                return id;
              },
            };
          },
        }));
      },
    },
  };
}

test("reads_every_top_level_window", () => {
  const S = services([11, 22, 33]);
  const got = zenWindowIds(S);
  assert.equal(got.ok, true);
  assert.deepEqual([...got.ids].sort(), ["11", "22", "33"]);
  assert.deepEqual(S.calls, [null]);
});

test("one_throwing_window_gives_not_ok", () => {
  assert.deepEqual(zenWindowIds(services([11, "throw", 33])), { ok: false });
  const broken = { wm: { getEnumerator: () => { throw new Error("x"); } } };
  assert.deepEqual(zenWindowIds(broken), { ok: false });
  assert.deepEqual(zenWindowIds(undefined), { ok: false });
});

test("ids_are_strings", () => {
  const got = zenWindowIds(services([7, 8n]));
  assert.ok(got.ids instanceof Set);
  for (const id of got.ids) {
    assert.equal(typeof id, "string");
  }
  assert.equal(got.ids.has("7"), true);
  assert.equal(got.ids.has("8"), true);
});

test("ids_seen_at_an_earlier_read_stay_zens", () => {
  const seen = new Set(["99"]);
  const got = zenWindowIds(services([11]), seen);
  assert.equal(got.ok, true);
  assert.deepEqual([...got.ids].sort(), ["11", "99"]);
  assert.deepEqual([...seen], ["99"]);
  assert.deepEqual(zenWindowIds(services(["throw"]), seen), { ok: false });
  assert.deepEqual([...zenWindowIds(services([11]), null).ids], ["11"]);
});
