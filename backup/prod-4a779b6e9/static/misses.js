/* 「우리가 틀린 것」 — 숫자와 문구를 여기 적지 않는다.
 *
 * 주의(중요): 설명은 사람이 검수해 적은 것이고 서버가 그대로 준다. 여기서
 *   문장을 만들면 화면이 검수하지 않은 말을 하게 된다 (R5).
 */
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function sums(c) {
    /* 순서가 곧 강조다. **없는 의무를 붙인 수 0** 이 우리가 자랑할 유일한
       수이므로 끝에 두고 따로 표시한다. */
    return [
      ["검수한 실상품", c.denominator, ""],
      ["품목을 맞힌 것", c.ok, ""],
      ["틀린 품목을 말한 것", c.wrong, ""],
      ["갈려서 고르지 않은 것", c.vague, ""],
      ["아무 말도 못 한 것", c.missed, ""],
      ["없는 의무를 말한 것", c.off_target, "zero"],
    ];
  }

  function card(r) {
    var said = (r.said || []).map(function (s) {
      return '<span class="mx-said">' + esc(s) + "</span>";
    }).join("");
    return (
      '<article class="mx-card">' +
        '<h3>' + esc(r.name) + "</h3>" +
        '<div class="mx-row"><span class="mx-k">저희가 말한 품목</span>' +
          '<span class="mx-v">' + (said || "-") + "</span></div>" +
        (r.kind ? '<div class="mx-row"><span class="mx-k">갈래</span>' +
                  '<span class="mx-v">' + esc(r.kind) + "</span></div>" : "") +
        (r.why ? '<p class="mx-why">' + esc(r.why) + "</p>" : "") +
      "</article>"
    );
  }

  fetch("/api/v1/misses")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) {
      if (!data || !data.counts || !data.counts.denominator) return;

      document.getElementById("sum").innerHTML = sums(data.counts).map(function (s) {
        return '<li class="' + s[2] + '"><b>' + esc(s[1]) + "</b><span>" +
               esc(s[0]) + "</span></li>";
      }).join("");

      document.getElementById("wrong").innerHTML = (data.wrong || []).map(card).join("");
      document.getElementById("vague").innerHTML = (data.vague || []).map(card).join("");
      document.getElementById("missed").innerHTML = (data.missed || []).map(function (r) {
        return "<li>" + esc(r.name) + "</li>";
      }).join("");
    })
    .catch(function () { /* 자료가 없어도 나머지 화면은 돈다 */ });
})();
