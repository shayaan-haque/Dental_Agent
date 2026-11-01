import test from "node:test";
import assert from "node:assert/strict";
import { getAppointments } from "./appointmentsApi.js";

test("saved appointments use the database endpoint with credentials and filters", async t => {
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/api/appointments?view=cancelled&limit=10&offset=20");
    assert.equal(options.credentials, "same-origin");
    assert.equal(options.cache, "no-store");
    return new Response(JSON.stringify({ items: [], has_more: false, limit: 10, offset: 20 }));
  });
  assert.deepEqual((await getAppointments({ view: "cancelled", offset: 20 })).items, []);
});

test("logged-out and backend errors are not mistaken for empty bookings", async t => {
  const mock = t.mock.method(globalThis, "fetch", async () => new Response("{}", { status: 401 }));
  await assert.rejects(getAppointments(), /log in again/);
  mock.mock.mockImplementation(async () => new Response(JSON.stringify({ detail: "Database unavailable" }), { status: 503 }));
  await assert.rejects(getAppointments(), /Database unavailable/);
});

test("malformed data is rejected and cancelled requests keep AbortError", async t => {
  const mock = t.mock.method(globalThis, "fetch", async () => new Response("{}"));
  await assert.rejects(getAppointments(), /invalid appointment list/);
  mock.mock.mockImplementation(async () => { throw new DOMException("Cancelled", "AbortError"); });
  await assert.rejects(getAppointments(), { name: "AbortError" });
});
