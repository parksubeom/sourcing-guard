/* 「왜 "모름" 이 나왔나」 — 문장을 여기서 만들지 않는다.
 *
 * 주의(가장 중요): 제목·본문·열리는 축 이름까지 전부 /api/v1/unknown-reasons
 *   가 준다. 같은 문장을 scorer 가 헤드라인으로도 쓰고 있어서, 여기서 지으면
 *   두 벌이 되고 한쪽만 고쳐질 때 화면이 낡은 말을 한다 (§6 · R5).
 *
 * 주의(중요): 이 파일이 만드는 글자는 **판정 두 개와 접속어**뿐이다 -
 *   "답하면 열립니다" / "이미 판단한 것입니다" / "→". 검사가 그 밖의 줄이
 *   없는지 본다.
 */
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  /* 갈래가 넷이다. **이 갈래가 이 화면의 요지다** - 모름이 끝인지 입구인지.
   *
   * 주의(가장 중요): 판정 문구를 여기서 고르지 않는다. 서버가 `verdict` 로
   *   준다. 처음에 "열린다 / 판단했다" 둘로만 갈랐더니 유해물질 미수록이
   *   "이미 판단한 것입니다" 가 됐는데 **그건 거짓**이다 - 우리 일이 남은
   *   것이다. 갈래는 서버가 안다. */
  function verdict(r) {
    var axes = (r.unlocks || []).map(function (u) {
      return '<span class="uk-ax">' + esc(u) + "</span>";
    }).join("");
    return '<p class="uk-v"><b>' + esc(r.verdict) + "</b>" +
           (axes ? '<span class="uk-axes">' + axes + "</span>" : "") + "</p>";
  }

  function card(r) {
    return '<article class="uk-card ' + esc(r.resolution || "settled") + '">' +
             "<h2>" + esc(r.title) + "</h2>" +
             "<p>" + esc(r.body) + "</p>" +
             verdict(r) +
           "</article>";
  }

  fetch("/api/v1/unknown-reasons")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) {
      if (!data || !data.reasons || !data.reasons.length) return;
      document.getElementById("list").innerHTML = data.reasons.map(card).join("");
    })
    .catch(function () { /* 자료가 없어도 머리말과 맺음은 남는다 */ });
})();
