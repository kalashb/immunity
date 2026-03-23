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
  const nameInput = document.getElementById("name-input");
  const voiceSelect = document.getElementById("voice-select");
  const resetBtn = document.getElementById("reset-btn");
  const clearLogsBtn = document.getElementById("clear-logs-btn");

  const PROCESSING_PHRASES = ["Reviewing...", "Escalating...", "Logging inquiry...", "Processing..."];
  const SILENT_AFTER_MS = 12000;
  const TTS_VOICE_STORAGE_KEY = "immunity-tts-voice";
  const FALLBACK_VOICES = ["F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3", "M4", "M5"];
  const COUNTER_LABELS = { patience: "Patience", irritation: "Irritation", disappointment: "Disappointment", administrative_load: "Mental load" };
  // Set labels from JS so they stay correct even if HTML was cached
  Object.keys(COUNTER_LABELS).forEach(function (key) {
    const counter = document.querySelector(".counter[data-key=\"" + key + "\"]");
    const labelEl = counter && counter.querySelector(".label");
    if (labelEl) labelEl.textContent = COUNTER_LABELS[key];
  });
  let eyeState = null;
  let silentTimer = null;
  let isProcessing = false;
  let currentAudio = null;
  let autoplayWarningShown = false;

  function doRandomBlink() {
    var lids = eyesContainer.querySelectorAll(".eye-lid");
    lids.forEach(function (lid) { lid.classList.add("blink"); });
    setTimeout(function () {
      lids.forEach(function (lid) { lid.classList.remove("blink"); });
    }, 120);
  }

  function scheduleRandomBlink() {
    var delay = 2000 + Math.random() * 3500;
    setTimeout(function () {
      if (!isProcessing) doRandomBlink();
      scheduleRandomBlink();
    }, delay);
  }

  function getState() {
    return fetch(API + "/state").then((r) => r.json());
  }

  function readSavedVoice() {
    try {
      return localStorage.getItem(TTS_VOICE_STORAGE_KEY) || "";
    } catch (_err) {
      return "";
    }
  }

  function saveSelectedVoice(voiceName) {
    try {
      localStorage.setItem(TTS_VOICE_STORAGE_KEY, voiceName || "");
    } catch (_err) {
      // Ignore storage failures; selection still works for this session.
    }
  }

  function getSelectedVoice() {
    return voiceSelect && voiceSelect.value ? voiceSelect.value : "";
  }

  function populateVoiceOptions(voices, preferredVoice) {
    if (!voiceSelect) return;

    const availableVoices = Array.isArray(voices) && voices.length ? voices : FALLBACK_VOICES;
    const savedVoice = readSavedVoice();
    const selectedVoice =
      availableVoices.indexOf(preferredVoice) !== -1 ? preferredVoice :
      availableVoices.indexOf(savedVoice) !== -1 ? savedVoice :
      availableVoices[0];

    voiceSelect.innerHTML = "";
    availableVoices.forEach(function (voiceName) {
      const option = document.createElement("option");
      option.value = voiceName;
      option.textContent = voiceName;
      voiceSelect.appendChild(option);
    });
    voiceSelect.value = selectedVoice;
    saveSelectedVoice(selectedVoice);
  }

  function loadVoiceOptions() {
    if (!voiceSelect) return Promise.resolve();

    return fetch(API + "/tts/voices")
      .then(function (r) {
        if (!r.ok) throw new Error("Voice list unavailable");
        return r.json();
      })
      .then(function (data) {
        populateVoiceOptions(data.voices, readSavedVoice() || data.default_voice || "");
      })
      .catch(function () {
        populateVoiceOptions(FALLBACK_VOICES, readSavedVoice() || "M1");
      });
  }

  function updateCounters(s) {
    ["patience", "irritation", "disappointment", "administrative_load"].forEach(function (key) {
      const valEl = document.getElementById("val-" + key);
      if (valEl && s[key] !== undefined) valEl.textContent = s[key];
      const counter = document.querySelector(".counter[data-key=\"" + key + "\"]");
      const labelEl = counter && counter.querySelector(".label");
      if (labelEl && COUNTER_LABELS[key]) labelEl.textContent = COUNTER_LABELS[key];
    });
  }

  function stateToEyeClass(s) {
    if (!s) return "state-neutral";
    if (s.is_blacklisted) return "state-blacklisting";
    if (s.administrative_load >= 75) return "state-overloaded";
    if (s.irritation >= 60) return "state-annoyed";
    if (s.disappointment >= 50 && s.irritation < 40) return "state-disappointed";
    return "state-neutral";
  }

  function setEyes(stateOrMode) {
    if (stateOrMode && typeof stateOrMode === "object") eyeState = stateOrMode;
    var next = typeof stateOrMode === "string"
      ? stateOrMode
      : (isProcessing ? "state-processing" : stateToEyeClass(stateOrMode));
    eyesContainer.className = "eyes-container " + next;
  }

  function setSilent(quiet) {
    if (quiet) {
      eyesContainer.className = "eyes-container state-silent";
    } else if (eyeState && typeof eyeState === "object") {
      setEyes(eyeState);
    } else {
      setEyes("state-neutral");
    }
  }

  function scheduleSilent() {
    if (silentTimer) clearTimeout(silentTimer);
    silentTimer = setTimeout(function () {
      if (!isProcessing) setSilent(true);
      silentTimer = null;
    }, SILENT_AFTER_MS);
  }

  function cancelSilent() {
    if (silentTimer) {
      clearTimeout(silentTimer);
      silentTimer = null;
    }
    setSilent(false);
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
    isProcessing = !!visible;
    if (visible) {
      cancelSilent();
      setEyes("state-processing");
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

  function stopResponseAudio() {
    if (!currentAudio) return;
    currentAudio.pause();
    currentAudio.src = "";
    currentAudio = null;
  }

  function playResponseAudio(audioUrl) {
    stopResponseAudio();
    if (!audioUrl) return;

    const audio = new Audio(audioUrl);
    audio.preload = "auto";
    audio.addEventListener("ended", function () {
      if (currentAudio === audio) currentAudio = null;
    });
    audio.addEventListener("error", function () {
      if (currentAudio === audio) currentAudio = null;
    });
    currentAudio = audio;

    const playPromise = audio.play();
    if (playPromise && typeof playPromise.catch === "function") {
      playPromise.catch(function () {
        if (!autoplayWarningShown) {
          addLog("Browser blocked voice playback.");
          autoplayWarningShown = true;
        }
      });
    }
  }

  function submit() {
    const question = (input.value || "").trim();
    if (!question) return;

    stopResponseAudio();
    submitBtn.disabled = true;
    setProcessing(true, PROCESSING_PHRASES[Math.floor(Math.random() * PROCESSING_PHRASES.length)]);

    var name = (nameInput && nameInput.value) ? nameInput.value.trim().slice(0, 80) : "";
    var voiceName = getSelectedVoice();
    fetch(API + "/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question, name: name, voice_name: voiceName }),
    })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (d) { throw new Error(d.detail || "Request failed"); });
        return r.json();
      })
      .then(function (data) {
        if (voiceSelect && data.voice_name) {
          if (voiceSelect.value !== data.voice_name) voiceSelect.value = data.voice_name;
          saveSelectedVoice(data.voice_name);
        }
        setProcessing(false);
        setResponse(data.reaction_text || "", data.answer_text || "");
        updateCounters(data.state);
        setEyes(data.state);
        scheduleSilent();
        triggerScreenEffect(data.screen_effect || "none");
        playResponseAudio(data.audio_url || "");
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
        stopResponseAudio();
        setProcessing(false);
        setResponse("System error.", "");
        addLog("Error: " + (err.message || "Request failed"));
      })
      .finally(function () {
        submitBtn.disabled = false;
      });
  }

  function doReset() {
    stopResponseAudio();
    fetch(API + "/reset", { method: "POST" })
      .then(function () { return getState(); })
      .then(function (s) {
        updateCounters(s);
        eyeState = s;
        setEyes(s);
        showBlacklist(false);
        scheduleSilent();
        setResponse("", "");
        addLog("Session reset. Next user may proceed.");
      })
      .catch(function () { addLog("Reset failed."); });
  }

  function doClearLogs() {
    fetch(API + "/clear-logs", { method: "POST" })
      .then(function () { addLog("Ticket and blacklist logs cleared."); })
      .catch(function () { addLog("Clear logs failed."); });
  }

  if (resetBtn) resetBtn.addEventListener("click", doReset);
  if (clearLogsBtn) clearLogsBtn.addEventListener("click", doClearLogs);
  if (voiceSelect) voiceSelect.addEventListener("change", function () {
    saveSelectedVoice(voiceSelect.value);
  });

  submitBtn.addEventListener("click", submit);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") submit();
  });
  input.addEventListener("focus", cancelSilent);

  // -- Physical buzzer polling ------------------------------------------------
  var BUZZER_POLL_MS = 150;
  var buzzerActive = true;

  function pollBuzzer() {
    if (!buzzerActive) return;
    fetch(API + "/buzzer")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.pressed && !isProcessing) {
          submit();
        }
      })
      .catch(function () { /* Arduino not connected — silent */ })
      .finally(function () {
        if (buzzerActive) setTimeout(pollBuzzer, BUZZER_POLL_MS);
      });
  }

  pollBuzzer();
  scheduleRandomBlink();
  loadVoiceOptions();

  getState()
    .then(function (s) {
      updateCounters(s);
      eyeState = s;
      setEyes(s);
      showBlacklist(s.is_blacklisted);
      scheduleSilent();
    })
    .catch(function () {
      updateCounters({
        patience: 70,
        irritation: 10,
        disappointment: 20,
        administrative_load: 0,
      });
      setEyes("state-neutral");
      scheduleSilent();
    });
})();
