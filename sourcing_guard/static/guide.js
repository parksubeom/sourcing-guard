/* [M-5] 카테고리 가이드 — 자료는 전부 서버에서 그린다. 숫자를 여기 적지 않는다. */
(function () {
  "use strict";
  var ALL = [];
  var body = document.getElementById("body");
  var none = document.getElementById("none");
  var q = document.getElementById("q");
  var only = document.getElementById("only");

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  /* "의류(39); 휴대폰(2)" → 알약 목록. 비어 있으면 아무것도 안 그린다. */
  function pills(raw, cls) {
    if (!raw) return "";
    return raw.split(";").map(function (p) {
      return '<span class="' + cls + '">' + esc(p.trim()) + "</span>";
    }).join("");
  }

  function row(r) {
    var pct = r.sampled ? r.matched_pct.toFixed(1) + "%" : "-";
    var count = r.sampled
      ? esc(r.matched) + " / " + esc(r.sampled) + "건 <b>" + pct + "</b>"
      : "표본 없음";
    var basis = [];
    if (r.grade_sources) basis.push(esc(r.grade_sources));
    if (r.annexes) basis.push(esc(r.annexes));
    if (r.jurisdictions) basis.push("소관 표기 관찰 — " + esc(r.jurisdictions));
    return (
      '<tr class="' + (r.observed ? "" : "gd-quiet") + '">' +
      "<th scope=\"row\"><span class=\"gd-cat\">" + esc(r.category) + "</span>" +
      '<span class="gd-parent">' + esc(r.parent) + "</span></th>" +
      '<td class="gd-n">' + count + "</td>" +
      "<td>" + (pills(r.items, "gd-pill") ||
        '<span class="gd-quiet-txt">이 표본에서는 붙은 품목이 없습니다</span>') + "</td>" +
      "<td>" + pills(r.grades, "gd-grade") + "</td>" +
      '<td class="gd-basis">' + (basis.join(" · ") || "") + "</td>" +
      "</tr>"
    );
  }

  function draw() {
    var term = (q.value || "").trim();
    var rows = ALL.filter(function (r) {
      if (only.checked && !r.observed) return false;
      if (!term) return true;
      return (r.category + " " + r.parent + " " + r.items).indexOf(term) >= 0;
    });
    body.innerHTML = rows.map(row).join("");
    none.hidden = rows.length > 0;
  }

  fetch("/api/v1/guide")
    .then(function (r) { return r.json(); })
    .then(function (d) {
      ALL = d.rows || [];
      var s = d.summary || {};
      document.getElementById("label").textContent = "이 표의 라벨 — " + (s.label || "");
      var cells = [
        ["카테고리", s.categories],
        ["말할 수 있는 카테고리", s.observed],
        ["아직 침묵하는 카테고리", s.silent],
        ["넣어 본 상품명", s.titles]
      ];
      document.getElementById("sum").innerHTML = cells.map(function (c) {
        return "<li><b>" + esc(c[1] == null ? "-" : c[1].toLocaleString()) +
          "</b><span>" + esc(c[0]) + "</span></li>";
      }).join("");
      draw();
    })
    .catch(function () {
      document.getElementById("label").textContent = "자료를 불러오지 못했습니다.";
    });

  q.addEventListener("input", draw);
  only.addEventListener("change", draw);
})();
