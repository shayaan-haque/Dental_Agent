import React, { useEffect, useState } from "react";
import { getAppointments } from "./appointmentsApi";
import "./appointments.css";

const filters = [
  ["upcoming", "Upcoming"], ["previous", "Previous"],
  ["cancelled", "Cancelled"], ["rescheduled", "Rescheduled"], ["all", "All bookings"],
];
const emptyMessages = {
  upcoming: "You have no upcoming appointments.",
  previous: "You have no previous bookings.",
  cancelled: "You have no cancelled bookings.",
  rescheduled: "You have no rescheduled bookings.",
  all: "You haven’t booked any appointments yet.",
};
const dateFormat = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", weekday: "short",
});
const timeFormat = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit",
});
const pageSize = 10;

export default function AppointmentsPanel({ user, authLoading, revision }) {
  const [view, setView] = useState("upcoming");
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    if (authLoading || !user) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setItems([]);
    setHasMore(false);
    getAppointments({ view, offset, limit: pageSize, signal: controller.signal })
      .then(data => {
        if (!controller.signal.aborted) {
          setItems(data.items);
          setHasMore(data.has_more);
        }
      })
      .catch(failure => {
        if (!controller.signal.aborted) setError(failure.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [user?.id, authLoading, view, offset, refresh, revision]);

  return (
    <section className="appointments-panel" aria-labelledby="appointments-title">
      <div className="appointments-heading">
        <div>
          <span className="eyebrow">YOUR DENTAL CARE, IN ONE PLACE</span>
          <h2 id="appointments-title">My appointments</h2>
          <p>Your saved bookings and history. All times are in Asia/Kolkata (IST).</p>
        </div>
        <button className="appointments-refresh" disabled={loading || authLoading || !user}
          onClick={() => setRefresh(value => value + 1)}>Refresh</button>
      </div>
      {authLoading ? <p role="status">Checking login…</p> : !user ? (
        <div className="appointments-empty"><p><a href="#/login">Log in</a> to see your saved appointments.</p></div>
      ) : <>
        <nav className="appointment-filters" aria-label="Appointment filters">
          {filters.map(([key, label]) => (
            <button key={key} aria-pressed={view === key} className={view === key ? "selected" : ""}
              onClick={() => { setView(key); setOffset(0); }}>{label}</button>
          ))}
        </nav>
        <div aria-live="polite" aria-busy={loading}>
          {loading ? <p className="appointments-loading" role="status">Loading your appointments…</p>
            : error ? <div className="error" role="alert">{error} <button onClick={() => setRefresh(value => value + 1)}>Try again</button></div>
            : !items.length ? <div className="appointments-empty">
              <span aria-hidden="true">◷</span><h3>{emptyMessages[view]}</h3>
              <p>Only bookings saved to your account appear here.</p>
              <a href="#/chat">Go to the assistant</a>
            </div> : (
              <ol className="appointment-list">
                {items.map(item => (
                  <li key={item.appointment_id} className="appointment-card">
                    <div className="appointment-card-top">
                      <div><p className="appointment-number">APPOINTMENT #{item.appointment_id}</p>
                        <h3>{item.doctor_name}</h3>
                        <p className="appointment-specialty">{item.specialization.replaceAll("_", " ")}</p></div>
                      <span className={`appointment-status status-${item.status}`}>{item.status}</span>
                    </div>
                    <div className="appointment-time">
                      <strong>{dateFormat.format(new Date(item.starts_at))}</strong>
                      <span>{timeFormat.format(new Date(item.starts_at))} – {timeFormat.format(new Date(item.ends_at))} IST</span>
                    </div>
                  </li>
                ))}
              </ol>
            )}
        </div>
        {!loading && !error && (offset > 0 || hasMore) && <nav className="appointment-pagination" aria-label="Appointment pages">
          <button disabled={offset === 0} onClick={() => setOffset(value => Math.max(0, value - pageSize))}>Previous page</button>
          <span>Page {Math.floor(offset / pageSize) + 1}</span>
          <button disabled={!hasMore} onClick={() => setOffset(value => value + pageSize)}>Next page</button>
        </nav>}
      </>}
      <p className="appointments-note">This page reads your saved bookings directly. It does not use AI tokens.
        Changed visits retain the old booking as rescheduled and show the replacement under Upcoming.</p>
    </section>
  );
}
