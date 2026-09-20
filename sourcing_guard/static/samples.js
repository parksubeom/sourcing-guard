/* 체험 표본 — 문구와 숫자를 여기 적지 않는다. 전부 /api/v1/samples 가 그린다.
 *
 * 주의(중요): 카드의 모든 문장은 우리 서버가 실제로 낸 /api/v1/scan 응답
 *   그대로다. 여기서 문장을 만들면 화면이 우리가 낸 적 없는 말을 한다 (R5).
 */
(function () {
  "use strict";

  var list = document.getElementById("list");
  var honestRecorded = document.getElementById("honest-recorded");
  var honestBaseline = document.getElementById("honest-baseline");

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  /* 주의(중요): 검사 화면의 SIGNAL_SHORT 와 **같은 낱말**이어야 한다. 같은
     신호를 두 화면이 다르게 부르면 셀러가 다른 것으로 읽는다
     (tests/test_experience_samples.py 가 두 표를 대조한다). */
  var TONE = { GREEN: "정상", AMBER: "주의", RED: "위험", UNKNOWN: "일부 확인" };
  /* 바닥 한 줄. index.html 의 LOOKUP 과 같은 낱말을 쓴다 - 같은 상태를 두
     화면이 다르게 부르면 셀러가 다른 것으로 읽는다. */
  var LOOKUP = { ok: "성공", stale: "이전 조회분", failed: "조회 실패",
                 not_attempted: "시도 안 함" };

  /* "2026-09-19T14:54:44+00:00" -> "2026-09-19". 날짜를 만들지 않는다 -
     서버가 준 값의 앞 열 글자만 쓴다. */
  function day(iso) { return String(iso || "").slice(0, 10); }

  function rowHtml(row) {
    if (!row) return "";
    return (
      '<li class="sx-row ' + esc(row.signal) + '">' +
        "<p>" + esc(row.statement_ko) + "</p>" +
        (row.source_url
          ? '<a href="' + esc(row.source_url) + '" target="_blank" rel="noopener">' +
            esc(row.source_label || "원문 보기") + "</a>"
          : "") +
      "</li>"
    );
  }

  function card(s) {
    var rows = rowHtml(s.cert_row) + rowHtml(s.recall_row);
    /* 유해물질은 **수만** 적는다. 열넷을 그대로 그리면 카드가 화면을 덮는다 -
       검사 화면이 FOLD_AT 으로 접는 것과 같은 이유다. */
    if (s.hazard_count) {
      rows +=
        '<li class="sx-row UNKNOWN"><p>이 품목에는 유해물질 기준 <b>' +
        esc(s.hazard_count) + "개</b>가 적용됩니다. 시험성적서로 확인이 필요합니다.</p>" +
        (s.hazard_source_url
          ? '<a href="' + esc(s.hazard_source_url) + '" target="_blank" rel="noopener">고시 원문</a>'
          : "") +
        "</li>";
    }

    var foot = [];
    if (s.extractor) foot.push("추출 <b>" + esc(s.extractor) + "</b>");
    if (s.gov_lookup) {
      foot.push("정부 조회 인증 <b>" + esc(LOOKUP[s.gov_lookup.cert] || s.gov_lookup.cert) +
                "</b> · 리콜 <b>" + esc(LOOKUP[s.gov_lookup.recall] || s.gov_lookup.recall) + "</b>");
    }

    /* 주의(중요): 표본 중 **우리가 못 맞힌 것**을 카드가 스스로 밝힌다.
       "여기 있는 것은 저희가 맞힌 예입니다" 라고만 두면 그 카드에는 거짓이
       된다 - 실측에서 초록불 한 장(봉제인형)이 미매칭 19 에 있었다.
       감추는 대신 적는다. 그게 이 제품이 파는 것과 같다. */
    var BUCKET = {
      missed: "이 상품은 저희가 품목을 매칭하지 못한 쪽에 속합니다",
      wrong: "이 상품은 저희가 품목을 틀리게 말한 쪽에 속합니다",
      vague: "이 상품은 품목이 갈려 저희가 고르지 않은 쪽에 속합니다"
    };
    var owned = s.bucket
      ? '<p class="sx-own">' + esc(BUCKET[s.bucket] || "") +
        ' <a href="/misses">우리가 틀린 것</a></p>'
      : "";

    return (
      '<article class="sx-card">' +
        '<header class="sx-head">' +
          '<span class="chip ' + esc(s.signal) + '"><span class="dot"></span>' +
            esc(TONE[s.signal] || s.signal) + "</span>" +
          "<h2>" + esc(s.title) + "</h2>" +
        "</header>" +
        '<p class="sx-headline">' + esc(s.headline) + "</p>" + owned +
        '<ul class="sx-rows">' + rows + "</ul>" +
        '<div class="sx-foot">' +
          '<a class="btn-t" href="/scan?sample=' + encodeURIComponent(s.id) + '">지금 다시 검사</a>' +
          "<span>" + foot.join(" · ") + "</span>" +
        "</div>" +
      "</article>"
    );
  }

  fetch("/api/v1/samples")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) {
      if (!data || !data.items || !data.items.length) {
        /* 빈 껍데기를 그리지 않는다. 없으면 구역째 숨긴다 (R3). */
        document.querySelector(".sx-lede").hidden = true;
        return;
      }
      honestRecorded.textContent =
        "이 결과는 저희가 " + day(data.recorded_at) +
        " 에 실제로 검사한 것입니다. 카드마다 '지금 다시 검사' 로 지금 상태를 보실 수 있습니다.";

      var b = data.baseline;
      if (b) {
        var pct = (b.ok / b.denominator * 100).toFixed(1);
        honestBaseline.textContent =
          "여기 있는 것은 저희가 맞힌 예입니다. 실상품 " + b.denominator +
          "건 기준 품목 적중 " + b.ok + "건(" + pct + "%)이고, 틀린 " + b.wrong +
          "건과 못 맞힌 " + b.missed + "건도 저장소에 공개돼 있습니다.";
        var link = document.createElement("a");
        link.href = "/misses";
        link.textContent = " 우리가 틀린 것 보기";
        honestBaseline.appendChild(link);
      }

      list.innerHTML = data.items.map(card).join("");
    })
    .catch(function () { /* 표본이 없어도 나머지 화면은 돈다 */ });
})();
