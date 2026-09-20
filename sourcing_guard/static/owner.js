/* 두 페이지가 공유하는 최소 헬퍼.
 *
 * 로그인이 없다. 감시 목록은 브라우저에 저장한 식별자로 묶는다 — 데모에
 * 계정을 요구하면 투표자가 그 자리에서 이탈한다. 대신 화면에 "이 브라우저에
 * 저장된 식별자로 관리된다"고 명시한다. 감시 목록은 이 서비스가 유일하게
 * 보증하는 것이라(기획서 §6.1), 어떻게 묶이는지를 감추면 안 된다.
 */
(function () {
  "use strict";

  var KEY = "sg.owner";

  function makeId() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return "o-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
  }

  window.SG = {
    /** 브라우저별 소유자 식별자. 저장소를 못 쓰면 세션 한정으로 동작한다. */
    ownerId: function () {
      try {
        var v = window.localStorage.getItem(KEY);
        if (!v) { v = makeId(); window.localStorage.setItem(KEY, v); }
        return v;
      } catch (e) {
        // 사생활 보호 모드 등으로 저장소가 막힌 경우. 등록은 되지만 이 탭을
        // 벗어나면 목록을 다시 찾을 수 없다 — 화면 문구가 그 사실을 적고 있다.
        window.SG._ephemeral = window.SG._ephemeral || makeId();
        return window.SG._ephemeral;
      }
    },

    /** innerHTML 로 그리기 전 반드시 통과시킨다.
     *  사용자가 붙여넣은 상세페이지 본문이 응답에 섞여 돌아온다. */
    esc: function (s) {
      return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
      });
    },

    /** 유해물질 축 한 줄. **이 문장의 오너는 여기 하나다.**
     *
     * 주의(중요): 검사 결과(index.html 의 접힌 줄)와 체험 표본 카드가 같은
     *   말을 해야 한다. 2026-09-20 까지 갈라져 있었다 - 한쪽은 "유해물질
     *   기준 N개가 적용됩니다. 시험성적서로 확인이 필요합니다", 다른 쪽은
     *   "실제 함유량은 상세페이지로 알 수 없습니다 - 공급처에 시험성적서를
     *   요청하세요". 뒤엣것이 셀러가 **할 일**을 적고 있어 그쪽으로 모은다.
     *
     * 주의: 수는 부르는 쪽이 센다. 여기서 세면 findings 를 두 번 훑는다.
     *
     * @param {number} n  적용되는 기준 건수
     * @param {string} [em]  수를 감쌀 태그 이름. 없으면 맨 글자
     */
    hazardSummary: function (n, em) {
      var open = em ? "<" + em + ">" : "";
      var close = em ? "</" + em + ">" : "";
      return "이 품목에는 유해물질 공통안전기준 " + open + n + close +
             "건이 적용됩니다. 실제 함유량은 상세페이지로 알 수 없습니다 — " +
             "공급처에 시험성적서를 요청하세요.";
    }
  };
})();
