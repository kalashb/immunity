(function () {
  const API = "/api";
  const eyesContainer = document.getElementById("eyes-container");
  const blacklistOverlay = document.getElementById("blacklist-overlay");
  const input = document.getElementById("input");
  const submitBtn = document.getElementById("submit");
  const processingEl = document.getElementById("processing");
  const processingText = document.getElementById("processing-text");
  const responseEl = document.getElementById("response");
  const responseReaction = document.getElementById("response-reaction");
  const responseAnswer = document.getElementById("response-answer");
  const eventLog = document.getElementById("event-log");

  const PROCESSING_PHRASES = ["Reviewing...", "Escalating...", "Logging inquiry...", "Processing..."];

  function getState() {
    return fetch(API + "/state").then((r) => r.json());
  }

  function updateCounters(s) {
    ["patience", "irritation", "curiosity", "administrative_load"].forEach(function (key) {
      const el = document.getElementById("val-" + key);
      if (el && s[key] !== undefined) el.textContent = s[key];
    });
  }

  function stateToEyeClass(s) {
    if (s.is_blacklisted) return "state-blacklisting";
    if (s.administrative_load >= 75) return "state-overloaded";
    if (s.irritation >= 60) return "state-annoyed";
    if (s.curiosity >= 50 && s.irritation < 40) return "state-curious";
    return "state-neutral";
  }

  function setEyes(state) {
    const next = stateToEyeClass(state);
    eyesContainer.className = "eyes-container " + next;
  }

  function triggerScreenEffect(effect) {
    if (effect === "minor_shake") {
      eyesContainer.classList.add("effect-shake");
      setTimeout(function () { eyesContainer.classList.remove("effect-shake"); }, 400);
    } else if (effect === "full_flash") {
      eyesContainer.classList.add("effect-flash");
      setTimeout(function () { eyesContainer.classList.remove("effect-flash"); }, 600);
    } else if (effect === "minor_glow") {
      eyesContainer.classList.add("effect-glow");
      setTimeout(function () { eyesContainer.classList.remove("effect-glow"); }, 600);
    }
  }

  function showBlacklist(show) {
    if (show) {
      blacklistOverlay.classList.remove("hidden");
    } else {
      blacklistOverlay.classList.add("hidden");
    }
  }

  function addLog(msg, isBlacklist) {
    const entry = document.createElement("div");
    entry.className = "entry" + (isBlacklist ? " blacklist" : "");
    entry.textContent = new Date().toLocaleTimeString() + " — " + msg;
    eventLog.appendChild(entry);
    eventLog.scrollTop = eventLog.scrollHeight;
    while (eventLog.children.length > 20) {
      eventLog.removeChild(eventLog.firstChild);
    }
  }

  function setProcessing(visible, text) {
    if (visible) {
      processingText.textContent = text || PROCESSING_PHRASES[0];
      processingEl.classList.remove("hidden");
      responseEl.classList.add("hidden");
    } else {
      processingEl.classList.add("hidden");
    }
  }

  function setResponse(reactionText, answerText) {
    responseReaction.textContent = reactionText || "";
    if (answerText && answerText.trim()) {
      responseAnswer.textContent = answerText.trim();
      responseAnswer.classList.remove("hidden");
    } else {
      responseAnswer.textContent = "";
      responseAnswer.classList.add("hidden");
    }
    responseEl.classList.remove("hidden");
  }

  function submit() {
    const question = (input.value || "").trim();
    if (!question) return;

    submitBtn.disabled = true;
    setProcessing(true, PROCESSING_PHRASES[Math.floor(Math.random() * PROCESSING_PHRASES.length)]);

    fetch(API + "/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question }),
    })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (d) { throw new Error(d.detail || "Request failed"); });
        return r.json();
      })
      .then(function (data) {
        setProcessing(false);
        setResponse(data.reaction_text || "", data.answer_text || "");
        updateCounters(data.state);
        setEyes(data.state);
        triggerScreenEffect(data.screen_effect || "none");
        if (data.blacklisted) {
          showBlacklist(true);
          addLog("BLACKLISTED: " + (data.ticket && data.ticket.case_number ? data.ticket.case_number : "—"), true);
        } else {
          addLog(
            (data.ticket && data.ticket.case_number ? data.ticket.case_number + " — " : "") +
              data.reaction_text
          );
        }
        input.value = "";
      })
      .catch(function (err) {
        setProcessing(false);
        setResponse("System error.", "");
        addLog("Error: " + (err.message || "Request failed"));
      })
      .finally(function () {
        submitBtn.disabled = false;
      });
  }

  submitBtn.addEventListener("click", submit);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") submit();
  });

  getState()
    .then(function (s) {
      updateCounters(s);
      setEyes(s);
      showBlacklist(s.is_blacklisted);
    })
    .catch(function () {
      updateCounters({
        patience: 70,
        irritation: 10,
        curiosity: 20,
        administrative_load: 0,
      });
    });
})();
