// 큐레이션·수집 인터랙션 (의존성 없는 vanilla JS — 오프라인/로컬에서도 동작)

// 관심(별표)은 단지 단위 — 같은 단지의 모든 ★ 버튼을 함께 갱신한다.
async function toggleStar(complexNo, btn) {
  const r = await fetch(`/complexes/${complexNo}/star`, { method: "POST" });
  const j = await r.json();
  if (!j.ok) { alert(j.error || "관심 등록 실패"); return; }
  document.querySelectorAll(`[data-cx-star="${complexNo}"]`).forEach((b) => {
    b.textContent = j.starred ? "★" : "☆";
    b.classList.toggle("on", j.starred);
  });
}

// 관심 단지 목록에서 해제 — 행을 즉시 제거한다.
async function unstarComplex(no, btn) {
  btn.disabled = true;
  const r = await fetch(`/complexes/${no}/star`, { method: "POST" });
  const j = await r.json();
  if (j.ok && !j.starred) {
    const tr = btn.closest("tr");
    if (tr) tr.remove();
  } else {
    btn.disabled = false;
    if (!j.ok) alert(j.error || "관심 해제 실패");
  }
}

async function toggleExclude(ck, btn) {
  const r = await fetch(`/curation/${ck}/exclude`, { method: "POST" });
  const j = await r.json();
  const tr = btn.closest("tr");
  if (tr) tr.classList.toggle("excluded", j.excluded);
  btn.textContent = j.excluded ? "복원" : "제외";
}

async function saveMemo(ck, inp) {
  const fd = new FormData();
  fd.append("memo", inp.value);
  await fetch(`/curation/${ck}/memo`, { method: "POST", body: fd });
  inp.classList.add("saved");
  setTimeout(() => inp.classList.remove("saved"), 900);
}

async function showHistory(ck) {
  const r = await fetch(`/listing/${ck}/history`);
  document.getElementById("histBody").innerHTML = await r.text();
  document.getElementById("histModal").showModal();
}

async function runNow(btn) {
  btn.disabled = true;
  btn.textContent = "수집 시작됨…";
  try {
    await fetch("/run", { method: "POST" });
  } catch (e) {}
  setTimeout(() => { location.href = "/runs"; }, 1800);
}

async function runDeals(btn) {
  btn.disabled = true;
  btn.textContent = "실거래 수집 시작됨…";
  try {
    await fetch("/run-deals", { method: "POST" });
  } catch (e) {}
  setTimeout(() => { location.href = "/runs"; }, 1800);
}

async function runPermits(btn) {
  btn.disabled = true;
  btn.textContent = "허가 수집 시작됨…";
  try {
    await fetch("/run-permits", { method: "POST" });
  } catch (e) {}
  setTimeout(() => { location.href = "/runs"; }, 1800);
}

// ── 추적 단지 추가/제거 ──────────────────────────────────────────────────────
async function addComplex(form) {
  const fd = new FormData(form);
  const no = (fd.get("complex_no") || "").trim();
  if (!/^\d+$/.test(no)) { alert("단지번호(숫자)를 입력하세요."); return false; }
  const btn = form.querySelector("button");
  btn.disabled = true;
  btn.textContent = "추가 중…";
  try {
    const r = await fetch("/complexes/add", { method: "POST", body: fd });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || "추가 실패");
    location.reload();
  } catch (e) {
    alert("추가 실패: " + e.message);
    btn.disabled = false;
    btn.textContent = "＋ 추적 추가";
  }
  return false;
}

async function untrackComplex(no, btn) {
  if (!confirm("이 단지를 정기 수집에서 제외할까요?\n기존 매물·관심표시는 유지됩니다.")) return;
  btn.disabled = true;
  const r = await fetch(`/complexes/${no}/untrack`, { method: "POST" });
  const j = await r.json();
  if (j.ok) location.reload();
  else { alert(j.error || "제외 실패"); btn.disabled = false; }
}

async function trackComplex(no, btn) {
  btn.disabled = true;
  const r = await fetch(`/complexes/${no}/track`, { method: "POST" });
  const j = await r.json();
  if (j.ok) location.reload();
  else { alert(j.error || "추적 실패"); btn.disabled = false; }
}

// 추적 단지 목록 클라이언트 필터(단지 많을 때 빠르게 찾기)
function filterTracking(q) {
  const needle = q.trim().toLowerCase();
  document.querySelectorAll("tr[data-cx]").forEach((tr) => {
    const hay = tr.getAttribute("data-cx") || "";
    tr.style.display = !needle || hay.includes(needle) ? "" : "none";
  });
}
