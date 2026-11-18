// Navigation for the two shells. The citizen shell shows only CITIZEN_NAV; the officer shell shows officerNav(role).

export const CITIZEN_NAV = [
  { page: "citizen-home", key: "nav.home" },          // labels are translation keys (four languages)
  { page: "self-check", key: "nav.self_check" },
  { page: "track", key: "nav.track" },
];

const OFFICER_NAV = [
  { page: "queue", label: "Queue" },
  { page: "intake", label: "Intake" },
  { page: "analytics", label: "Analytics" },
  { page: "simulator", label: "Simulator" },
];

// Officer-shell pages each staff role may open. Case pages (case, audit, award) are reached from the queue.
const ACCESS = {
  officer: ["queue", "case", "audit", "award", "intake", "analytics", "simulator"],
  clerk: ["queue", "case", "intake", "analytics"],
  admin: ["analytics", "simulator"],
};


export function allowed(role, page) {
  return (ACCESS[role] || []).includes(page);
}

export function officerNav(role) {
  return OFFICER_NAV.filter((n) => allowed(role, n.page));
}

export function homePage(role) {
  return officerNav(role)[0]?.page || null;
}
