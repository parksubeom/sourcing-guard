/* 「내 카테고리가 되나요?」 — 답은 셋뿐이고 **전부 자료에서 갈린다.**
 *
 * 주의(가장 중요): 새 분류표를 만들지 않는다. `/api/v1/guide` 가 이미 주는
 *   `matched` 와 `jurisdictions` 로 갈린다 - 카테고리 198개를 손으로 나누면
 *   그것은 오너와 실측이 필요한 **새 판단표**다.
 *
 * 주의(가장 중요): **퍼센트를 그리지 않는다.** 응답에 `matched_pct` 가 있어도
 *   쓰지 않는다. 그 수는 배치 경로(상품명 글자만 · AI 안 씀)의 수이고,
 *   셀러의 검사는 단건 경로(상세페이지 전체 · AI 추출)라 **다른 경로의 수**다.
 *   "나는 14% 확률이구나" 로 읽히면 틀린 것을 읽은 것이다.
 *   검사가 화면에 `%` 가 0건인지 단정한다.
 */
(function () {
  "use strict";

  var ALL = [];
  var q = document.getElementById("q");
  var answer = document.getElementById("answer");
  var hint = document.getElementById("hint");

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  /* 소관 표기 관찰 건수의 합.
   *
   * 주의(가장 중요): 문턱이 **10건**이다. 실측 분포(2026-09-20 · 198 카테고리):
   *
   *     10건 이상  8개   선케어 28 · 남성화장품 22 · 카시트 20 · 스킨케어 19 ·
   *                     여성가방 17 · 마스크/팩 13 · 뷰티소품 13 · 여행용가방 10
   *     1~9건     26개  베이스메이크업 8 · 바디케어 7 · 향수 4 · 지갑 3 ·
   *                     종교용품 3 · 남성가방 1 · 침실가구 1
   *
   *   1~3건은 상품명에 낱말이 섞인 잡음이다(남성가방에 화장품법 1건).
   *   주의: 경계가 깨끗하지는 않다 - 베이스메이크업 8 · 바디케어 7 은 화장품
   *     카테고리라 **진짜 신호일 가능성이 높은데** 문턱 아래로 떨어진다.
   *     문턱을 내리는 쪽을 검토할 때 이 두 줄이 비교군이다. */
  var JURIS_MIN = 10;

  function jurisCount(raw) {
    var n = 0, m, re = /\((\d+)건\)/g;
    while ((m = re.exec(raw || ""))) n += parseInt(m[1], 10);
    return n;
  }

  /* "의류 이외의 섬유제품(8); 의류(3)" → "의류 이외의 섬유제품".
     맨 앞이 가장 많이 나온 품목이다. 수는 떼고 이름만 쓴다. */
  function topItem(raw) {
    var first = String(raw || "").split(";")[0].trim();
    return first.replace(/\(\d+\)\s*$/, "").trim();
  }

  function card(r) {
    var out = "";
    var item = topItem(r.items);

    if (r.matched > 0 && item) {
      out +=
        '<div class="gd-a ok">' +
          "<h2>「" + esc(r.category) + "」 — 다룹니다</h2>" +
          "<p>이 카테고리 상품명에서 저희가 찾은 품목은 주로 " +
            "<strong>「" + esc(item) + "」</strong>이었습니다.</p>" +
          '<p class="gd-go"><a class="btn" href="/scan">내 상품 검사하기 →</a></p>' +
        "</div>";
    } else {
      out +=
        '<div class="gd-a quiet">' +
          "<h2>「" + esc(r.category) + "」 — 이 표본에서는 품목을 찾지 못했습니다</h2>" +
          "<p>저희가 다루는 것은 전기용품 · 생활용품 · 어린이제품입니다.</p>" +
          // 주의(가장 중요): **이 한 줄이 R3 다.** 못 찾은 것은 우리가 못 찾은
          //   것이지 그 카테고리에 의무가 없다는 뜻이 아니다. 옛 표 화면이
          //   이 말을 하고 있었고, 표를 내리면서 같이 사라질 뻔했다 -
          //   검사가 잡았다.
          "<p><strong>이 카테고리에 안전관리 의무가 없다는 뜻은 아닙니다.</strong> " +
            "저희가 못 찾은 것입니다.</p>" +
          // 주의(중요): 이 단서가 빠지면 "안 다룹니다" 로 읽힌다. 표본은
          //   상품명 글자만 본 것이고, 상세페이지에는 재질·대상연령처럼
          //   상품명에 없는 정보가 있다.
          "<p>다만 이 표본은 <strong>상품명 글자만</strong> 본 것입니다. " +
            "상세페이지에는 재질·대상연령처럼 상품명에 없는 정보가 있어서, " +
            "직접 넣으면 결과가 다를 수 있습니다.</p>" +
          '<p class="gd-go"><a class="btn" href="/scan">그래도 넣어 보기 →</a></p>' +
        "</div>";
    }

    // 덧붙임. 주의(가장 중요): **"우리가 안 다룹니다" 로 쓰지 않는다.**
    //   카시트는 자동차관리법 20건이 관찰되지만 **어린이제품이기도 하다.**
    //   소관 관찰만 보고 밀어내면 진짜 대상 상품을 내보낸다.
    if (jurisCount(r.jurisdictions) >= JURIS_MIN) {
      out += '<p class="gd-also">이 카테고리 상품명에서 <strong>' +
             esc(r.jurisdictions) + "</strong> 표기가 관찰됐습니다. " +
             "해당 기준도 함께 확인하셔야 할 수 있습니다.</p>";
    }
    return out;
  }

  function draw() {
    var term = (q.value || "").trim();
    if (!term) { answer.innerHTML = ""; return; }
    var hits = ALL.filter(function (r) {
      return (r.category + " " + r.parent).indexOf(term) >= 0;
    });
    if (!hits.length) {
      answer.innerHTML = '<div class="gd-a quiet"><h2>「' + esc(term) +
        "」 — 도매 카테고리 목록에 없습니다</h2>" +
        "<p>카테고리 이름 대신 상품을 직접 넣어 보시는 편이 빠릅니다.</p>" +
        '<p class="gd-go"><a class="btn" href="/scan">내 상품 검사하기 →</a></p></div>';
      return;
    }
    answer.innerHTML = hits.slice(0, 6).map(card).join("");
  }

  fetch("/api/v1/guide")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (!d) throw new Error("no data");
      ALL = d.rows || [];
      var s = d.summary || {};
      // 숫자는 **양**이지 정확도가 아니다. 서버에서 온다.
      document.getElementById("lede").textContent =
        "도매 카테고리 " + (s.categories || 0).toLocaleString() +
        "개 · 상품명 " + (s.titles || 0).toLocaleString() + "개를 실제로 넣어 봤습니다.";
      var often = ["유아동잡화", "남성가방", "생활용품", "디지털/가전", "출산"];
      var have = often.filter(function (n) {
        return ALL.some(function (r) { return r.category === n || r.parent === n; });
      });
      hint.innerHTML = have.length
        ? "자주 찾는 것: " + have.map(function (n) {
            return '<button type="button" class="gd-chip" data-t="' + esc(n) + '">' +
                   esc(n) + "</button>";
          }).join("")
        : "";
      hint.querySelectorAll("button[data-t]").forEach(function (b) {
        b.addEventListener("click", function () {
          q.value = b.getAttribute("data-t");
          draw();
        });
      });
    })
    .catch(function () {
      document.getElementById("lede").textContent = "자료를 불러오지 못했습니다.";
    });

  q.addEventListener("input", draw);
})();
