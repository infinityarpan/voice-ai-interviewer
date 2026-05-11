let pc = null;
    let dc = null;
    let voiceStream = null;
    let localStream = null;
    let meterStream = null;
    let micTrack = null;
    let currentQuestion = "";
    let currentProvider = "mock";
    let voiceConnectionId = 0;
    let voiceConnecting = false;
    let interviewActive = false;
    let recognition = null;
    let answerStartedAt = null;
    let lastAnswerDurationSeconds = null;
    let lastMicPercent = 0;
    let isRecording = false;
    let isArmingAnswer = false;
    let awaitingTranscript = false;
    let assistantAudioActive = false;
    let assistantAudioPending = false;
    let pendingTranscriptItemId = null;
    let speechDetected = false;
    let lastSpeechAt = null;
    let autoStartTimer = null;
    let autoSubmitting = false;
    let debugEvents = [];
    let audioContext = null;
    let analyser = null;
    let micLevelTimer = null;

    const MIN_RECORDING_MS = 1200;
    const AUTO_SPEECH_LEVEL = 3;
    const AUTO_SILENCE_MS = 1400;
    const AUTO_START_AFTER_QUESTION_MS = 250;
    const AUTO_SUBMIT_DELAY_MS = 100;
    const AUTO_MAX_RECORDING_MS = 120000;
    const TRANSCRIPTION_PROMPT = "Verbatim English transcription only. Write exactly what the candidate says, including short tests like hello. Do not answer the interview question, infer missing words, summarize, rewrite, or add technical content that was not spoken. If the audio is silence or unclear noise, return an empty transcript.";

    const $ = (id) => document.getElementById(id);
    const setStatus = (value) => {
      const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
      console.log("[voice-test]", value);
      $("uiState").textContent = typeof value === "string"
        ? value
        : value.ui || value.voice || value.auto || value.recording || value.transcription || value.connected || value.interview || "Updated";
    };

    function updateControls() {
      $("startInterview").disabled = voiceConnecting || interviewActive;
      $("endInterview").disabled = !voiceConnecting && !interviewActive && !dc && !pc;
    }

    function rememberRealtimeEvent(event) {
      if (!event || !event.type) return;
      const entry = { type: event.type };
      if (event.transcript) entry.transcript = event.transcript;
      if (event.delta) entry.delta = event.delta;
      if (event.error) entry.error = event.error;
      debugEvents = [entry, ...debugEvents].slice(0, 12);
    }

    function setVoiceStatus(value) {
      console.log("[voice-test:voice]", value);
      if (typeof value === "string") {
        setStatus({ voice: value });
        return;
      }
      setStatus(value);
    }

    function markLatency(name, detail = {}) {
      const event = {
        type: "latency_mark",
        name,
        at_ms: Math.round(performance.now()),
        ...detail
      };
      console.log("[voice-latency]", event);
      sendVoiceStream(event);
    }

    function sendVoiceStream(event) {
      if (!voiceStream || voiceStream.readyState !== WebSocket.OPEN) return false;
      voiceStream.send(JSON.stringify(event));
      return true;
    }

    function connectVoiceStream(sessionId) {
      if (voiceStream) voiceStream.close();
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      voiceStream = new WebSocket(`${protocol}://${window.location.host}/interviews/${sessionId}/voice/stream`);
      voiceStream.onopen = () => markLatency("voice_stream_open");
      voiceStream.onmessage = (message) => {
        try { handleVoiceStreamMessage(JSON.parse(message.data)); } catch (error) { console.warn(error); }
      };
      voiceStream.onclose = () => {
        voiceStream = null;
        console.log("[voice-stream] closed");
      };
      voiceStream.onerror = (error) => console.warn("[voice-stream]", error);
    }

    function handleVoiceStreamMessage(message) {
      if (message.type === "voice_turn_result") {
        markLatency("backend_response_received");
        autoSubmitting = false;
        applyVoiceTurnResult(message.payload);
      } else if (message.type === "error") {
        autoSubmitting = false;
        setStatus(message);
      }
    }

    function transcriptLooksInvalid(text) {
      const trimmed = (text || "").trim();
      const asciiWords = trimmed.match(/[A-Za-z]{2,}/g) || [];
      return trimmed.length === 0 || asciiWords.length === 0;
    }

    function transcriptLooksHallucinatedForDuration(text) {
      const words = (text || "").trim().split(/\s+/).filter(Boolean);
      return lastAnswerDurationSeconds !== null && lastAnswerDurationSeconds < 4 && words.length > 12;
    }

    function startMicMeter(stream) {
      if (!stream || audioContext) return;
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      audioContext.resume().catch(() => {});
      const source = audioContext.createMediaStreamSource(stream);
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      micLevelTimer = setInterval(() => {
        if (!analyser) return;
        analyser.getByteTimeDomainData(samples);
        let sum = 0;
        for (const value of samples) {
          const centered = value - 128;
          sum += centered * centered;
        }
        const rms = Math.sqrt(sum / samples.length) / 128;
        const percent = Math.round(rms * 100);
        lastMicPercent = percent;
        $("micLevel").textContent = `Mic level: ${percent}% ${isRecording ? "(recording)" : "(standby)"}`;
        if (isRecording && autoModeEnabled()) handleAutoVoiceActivity(percent);
      }, 150);
    }

    function stopMicMeter() {
      if (micLevelTimer) clearInterval(micLevelTimer);
      micLevelTimer = null;
      analyser = null;
      if (audioContext) audioContext.close().catch(() => {});
      audioContext = null;
      $("micLevel").textContent = "Mic level: idle";
    }

    async function loadAudioInputDevices() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
      const selectedDeviceId = $("micDevice").value;
      const devices = await navigator.mediaDevices.enumerateDevices();
      const inputs = devices.filter((device) => device.kind === "audioinput");
      $("micDevice").innerHTML = "";
      for (const device of inputs) {
        const option = document.createElement("option");
        option.value = device.deviceId;
        option.textContent = device.label || `Microphone ${$("micDevice").options.length + 1}`;
        if (device.deviceId === selectedDeviceId) option.selected = true;
        $("micDevice").appendChild(option);
      }
    }

    function selectedAudioConstraints() {
      const deviceId = $("micDevice").value;
      const audio = {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      };
      if (deviceId) audio.deviceId = { exact: deviceId };
      return { audio };
    }

    function autoModeEnabled() {
      return currentProvider === "openai_realtime";
    }

    function cancelAssistantAudio() {
      if ("speechSynthesis" in window) speechSynthesis.cancel();
      if (assistantAudioActive || assistantAudioPending) {
        sendRealtimeEvent({ type: "response.cancel" });
        sendRealtimeEvent({ type: "output_audio_buffer.clear" });
        assistantAudioActive = false;
        assistantAudioPending = false;
      }
    }

    function clearAutoStartTimer() {
      if (autoStartTimer) clearTimeout(autoStartTimer);
      autoStartTimer = null;
    }

    function scheduleAutoStartAfterQuestion() {
      clearAutoStartTimer();
      if (!interviewActive || !autoModeEnabled() || !currentQuestion || isRecording || isArmingAnswer || awaitingTranscript) return;
      autoStartTimer = setTimeout(() => {
        if (interviewActive && autoModeEnabled() && !isRecording && !isArmingAnswer && !awaitingTranscript) {
          startAnswer({ auto: true });
        }
      }, AUTO_START_AFTER_QUESTION_MS);
      markLatency("listening_scheduled", { delay_ms: AUTO_START_AFTER_QUESTION_MS });
      setVoiceStatus({
        auto: "waiting_to_listen",
        note: "Hands-free mode will start listening after the question audio settles."
      });
    }

    function handleAutoVoiceActivity(percent) {
      const now = Date.now();
      const durationMs = answerStartedAt ? now - answerStartedAt : 0;
      if (percent >= AUTO_SPEECH_LEVEL) {
        if (!speechDetected) markLatency("first_speech_detected", { mic_level_percent: percent });
        speechDetected = true;
        lastSpeechAt = now;
      }
      if (speechDetected && lastSpeechAt && now - lastSpeechAt >= AUTO_SILENCE_MS && durationMs >= MIN_RECORDING_MS) {
        markLatency("silence_detected", { duration_ms: durationMs });
        stopAnswer({ auto: true });
        return;
      }
      if (durationMs >= AUTO_MAX_RECORDING_MS) {
        stopAnswer({ auto: true });
      }
    }

    function scheduleAutoSubmit() {
      if (!autoModeEnabled() || autoSubmitting) return;
      autoSubmitting = true;
      markLatency("auto_submit_scheduled", { delay_ms: AUTO_SUBMIT_DELAY_MS });
      setTimeout(() => submitAnswer({ auto: true }), AUTO_SUBMIT_DELAY_MS);
    }

    async function loadProviderStatus() {
      try {
        const response = await fetch("/interviews/voice/status");
        const status = await response.json();
        $("providerStatus").textContent = `${status.provider} (${status.available ? "available" : "not available"})`;
        currentProvider = status.provider === "openai_realtime" ? "openai_realtime" : "mock";
      } catch (error) {
      $("providerStatus").textContent = "Unable to read backend voice provider.";
      }
    }

    function speakLocally(text) {
      if (!("speechSynthesis" in window)) return;
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1;
      speechSynthesis.cancel();
      speechSynthesis.speak(utterance);
    }

    function sendRealtimeSpeak(text) {
      cancelAssistantAudio();
      if (!dc || dc.readyState !== "open") {
        speakLocally(text);
        return;
      }
      markLatency("tts_requested");
      assistantAudioPending = true;
      dc.send(JSON.stringify({
        type: "response.create",
        response: {
          conversation: "none",
          input: [{
            type: "message",
            role: "user",
            content: [{ type: "input_text", text: "Speak exactly this question and nothing else: " + text }]
          }],
          instructions: "Speak exactly this backend-provided interview question and nothing else. Do not ask follow-ups or add commentary.",
          output_modalities: ["audio"]
        }
      }));
    }

    function sendRealtimeEvent(event) {
      if (!dc || dc.readyState !== "open") return false;
      dc.send(JSON.stringify(event));
      return true;
    }

    function updateRealtimeSession() {
      sendRealtimeEvent({
        type: "session.update",
        session: {
          audio: {
            input: {
              transcription: {
                model: "gpt-4o-transcribe",
                language: "en",
                prompt: TRANSCRIPTION_PROMPT
              },
              noise_reduction: { type: "near_field" },
              turn_detection: null
            }
          }
        }
      });
    }

    function handleRealtimeEvent(event) {
      rememberRealtimeEvent(event);
      if (event.type === "error") {
        assistantAudioPending = false;
        setVoiceStatus(event);
        return;
      }
      if (event.type === "output_audio_buffer.started") {
        markLatency("tts_audio_started");
        assistantAudioPending = false;
        assistantAudioActive = true;
        $("voiceHint").textContent = "Speaking the backend question.";
        return;
      }
      if (event.type === "output_audio_buffer.stopped" || event.type === "output_audio_buffer.cleared") {
        markLatency(event.type === "output_audio_buffer.stopped" ? "tts_audio_stopped" : "tts_audio_cleared");
        assistantAudioPending = false;
        assistantAudioActive = false;
        if (!isRecording) $("voiceHint").textContent = "Question playback is done. Listening will start automatically.";
        if (event.type === "output_audio_buffer.stopped" && interviewActive) scheduleAutoStartAfterQuestion();
        return;
      }
      if (event.type === "input_audio_buffer.committed") {
        markLatency("audio_committed");
        if (event.item_id) pendingTranscriptItemId = event.item_id;
        setVoiceStatus({ audio: "committed", note: "Waiting for OpenAI Realtime transcription." });
        return;
      }
      if (event.type === "conversation.item.input_audio_transcription.failed") {
        if (pendingTranscriptItemId && event.item_id && event.item_id !== pendingTranscriptItemId) return;
        awaitingTranscript = false;
        pendingTranscriptItemId = null;
        setVoiceStatus({
          transcription: "failed",
          error: event.error || null,
          note: "No usable speech was transcribed. Re-record or type the transcript manually."
        });
        return;
      }
      if (event.type === "conversation.item.input_audio_transcription.delta" && event.delta) {
        if (!isRecording && !awaitingTranscript) return;
        $("transcript").value = (($("transcript").value || "") + " " + (event.transcript || event.delta)).trim();
      }
      if (event.type === "conversation.item.input_audio_transcription.completed") {
        const transcript = (event.transcript || "").trim();
        markLatency("final_transcript_received", { chars: transcript.length });
        if (pendingTranscriptItemId && event.item_id && event.item_id !== pendingTranscriptItemId) {
          setVoiceStatus({
            transcription: "ignored",
            ignoredTranscript: transcript,
            note: "Ignored transcription for an older committed audio item."
          });
          return;
        }
        if (!awaitingTranscript) {
          setVoiceStatus({
            transcription: "ignored",
            ignoredTranscript: transcript,
            note: "Ignored a stray transcript because no stopped answer was waiting for transcription."
          });
          return;
        }
        awaitingTranscript = false;
        pendingTranscriptItemId = null;
        if (transcriptLooksInvalid(transcript)) {
          $("transcript").value = "";
          setVoiceStatus({
            transcription: "ignored",
            ignoredTranscript: transcript,
            note: "Only a tiny/noisy fragment was detected. Re-record, speak closer to the mic, or type the transcript manually."
          });
          return;
        }
        if (transcriptLooksHallucinatedForDuration(transcript)) {
          $("transcript").value = "";
          setVoiceStatus({
            transcription: "ignored",
            ignoredTranscript: transcript,
            duration_seconds: lastAnswerDurationSeconds,
            note: "Rejected an implausibly long transcript for a very short recording. This usually means the transcription model invented an answer instead of transcribing speech."
          });
          return;
        }
        $("transcript").value = transcript;
        setVoiceStatus({ transcription: "completed", transcript });
        scheduleAutoSubmit();
      }
    }

    function startLocalRecognition() {
      const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!Recognition) {
        setStatus("Mock mode: browser SpeechRecognition is unavailable. Type or paste the transcript manually.");
        return;
      }
      recognition = new Recognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = "en-US";
      recognition.onresult = (event) => {
        let finalText = "";
        let interimText = "";
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const text = event.results[index][0].transcript;
          if (event.results[index].isFinal) finalText += text + " ";
          else interimText += text + " ";
        }
        $("transcript").value = (($("transcript").dataset.final || "") + finalText + interimText).trim();
        if (finalText) $("transcript").dataset.final = (($("transcript").dataset.final || "") + finalText).trim() + " ";
      };
      recognition.onerror = (event) => {
        if (event.error === "no-speech") {
          setStatus({
            speechRecognitionError: "no-speech",
            note: "This is browser mock STT, not OpenAI Realtime. Speak closer to the mic, allow microphone access, or type the transcript manually. For real STT set VOICE_PROVIDER=openai_realtime and restart Uvicorn."
          });
          return;
        }
        setStatus({ speechRecognitionError: event.error });
      };
      recognition.start();
    }

    function stopLocalRecognition() {
      if (recognition) recognition.stop();
      recognition = null;
    }

    function disconnectVoice(options = {}) {
      voiceConnectionId += 1;
      voiceConnecting = false;
      if (options.ended) interviewActive = false;
      cancelAssistantAudio();
      if (dc) dc.close();
      if (voiceStream) voiceStream.close();
      if (pc) pc.close();
      const remoteAudio = $("remoteAudio");
      if (remoteAudio.srcObject) {
        remoteAudio.srcObject.getTracks().forEach((track) => track.stop());
        remoteAudio.srcObject = null;
      }
      if (localStream) localStream.getTracks().forEach((track) => track.stop());
      if (meterStream) meterStream.getTracks().forEach((track) => track.stop());
      stopLocalRecognition();
      stopMicMeter();
      clearAutoStartTimer();
      isRecording = false;
      isArmingAnswer = false;
      awaitingTranscript = false;
      assistantAudioActive = false;
      assistantAudioPending = false;
      pendingTranscriptItemId = null;
      speechDetected = false;
      lastSpeechAt = null;
      autoSubmitting = false;
      answerStartedAt = null;
      lastAnswerDurationSeconds = null;
      dc = null; pc = null; voiceStream = null; localStream = null; meterStream = null; micTrack = null;
      $("voiceHint").textContent = options.ended ? "Interview ended. Voice disconnected." : "Voice provider disconnected.";
      updateControls();
      if (!options.keepStatus) setStatus(options.status || "Disconnected.");
    }

    $("startInterview").onclick = async () => {
      disconnectVoice({ keepStatus: true });
      voiceConnecting = true;
      interviewActive = false;
      updateControls();
      const payload = {
        job_description: $("jobDescription").value,
        candidate_profile: $("candidateProfile").value,
        role_level: "Associate",
        role_title: "Voice Test Role",
        required_skills: $("requiredSkills").value.split(",").map((item) => item.trim()).filter(Boolean)
      };
      const response = await fetch("/interviews/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) {
        voiceConnecting = false;
        updateControls();
        return setStatus(data);
      }
      $("sessionId").value = data.session_id;
      currentQuestion = data.first_question.question_text;
      $("questionText").textContent = currentQuestion;
      setStatus({ interview: "started", voice: "connecting", session: data });
      connectVoiceStream(data.session_id);
      await connectVoice(data.session_id, voiceConnectionId);
    };

    async function connectVoice(sessionId, connectionId) {
      try {
        if (!sessionId) return setStatus("Start or enter a session first.");
        const response = await fetch(`/interviews/${sessionId}/voice/realtime-token`, { method: "POST" });
        const token = await response.json();
        if (connectionId !== voiceConnectionId) return;
        if (!response.ok) {
          voiceConnecting = false;
          updateControls();
          return setStatus(token);
        }
        currentProvider = token.provider;
        currentQuestion = token.question_text;
        $("questionText").textContent = currentQuestion;
        if (token.provider === "mock") {
          $("voiceHint").textContent = "Connected in mock mode. Hands-free answer automation requires OpenAI Realtime.";
          voiceConnecting = false;
          interviewActive = true;
          updateControls();
          setStatus({ connected: "mock", note: "Mock mode only plays the current question locally. Use VOICE_PROVIDER=openai_realtime for hands-free voice interviews.", token });
          speakLocally(currentQuestion);
          return;
        }
        $("voiceHint").textContent = "Connected to OpenAI Realtime. Hands-free mode will listen automatically after each question.";

        pc = new RTCPeerConnection();
        $("remoteAudio").srcObject = new MediaStream();
        pc.ontrack = (event) => $("remoteAudio").srcObject = event.streams[0];
        localStream = await navigator.mediaDevices.getUserMedia(selectedAudioConstraints());
        if (connectionId !== voiceConnectionId) {
          localStream.getTracks().forEach((track) => track.stop());
          return;
        }
        await loadAudioInputDevices();
        micTrack = localStream.getAudioTracks()[0];
        meterStream = new MediaStream([micTrack.clone()]);
        micTrack.enabled = false;
        startMicMeter(meterStream);
        pc.addTrack(micTrack);
        dc = pc.createDataChannel("oai-events");
        dc.onopen = () => {
          if (connectionId !== voiceConnectionId) return;
          voiceConnecting = false;
          interviewActive = true;
          updateControls();
          updateRealtimeSession();
          sendRealtimeSpeak(currentQuestion);
        };
        dc.onmessage = (message) => {
          if (connectionId !== voiceConnectionId) return;
          try { handleRealtimeEvent(JSON.parse(message.data)); } catch (error) { console.warn(error); }
        };
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        const sdpResponse = await fetch(token.realtime_url, {
          method: "POST",
          body: offer.sdp,
          headers: {
            Authorization: `Bearer ${token.client_secret}`,
            "Content-Type": "application/sdp"
          }
        });
        const answer = { type: "answer", sdp: await sdpResponse.text() };
        if (connectionId !== voiceConnectionId) return;
        await pc.setRemoteDescription(answer);
        setStatus({ connected: "openai_realtime", token: { ...token, client_secret: "redacted" } });
      } catch (error) {
        voiceConnecting = false;
        updateControls();
        setStatus({ ui: "Voice connection failed", detail: String(error) });
      }
    }

    function startAnswer(options = {}) {
      if (isRecording || isArmingAnswer) return options.auto ? null : setVoiceStatus("Already recording.");
      clearAutoStartTimer();
      $("transcript").value = "";
      $("transcript").dataset.final = "";
      awaitingTranscript = false;
      pendingTranscriptItemId = null;
      speechDetected = false;
      lastSpeechAt = null;
      lastAnswerDurationSeconds = null;
      if (currentProvider === "mock") {
        answerStartedAt = Date.now();
        isRecording = true;
        startLocalRecognition();
        setStatus("Mock mode cannot run the hands-free Realtime answer loop.");
        return;
      }
      if (!dc || dc.readyState !== "open") {
        return setStatus("Connect OpenAI Realtime voice before starting an answer.");
      }
      if (!micTrack) {
        return setStatus("Microphone track is unavailable. Disconnect and reconnect voice.");
      }

      if ("speechSynthesis" in window) speechSynthesis.cancel();
      isArmingAnswer = true;
      if (assistantAudioActive) {
        sendRealtimeEvent({ type: "response.cancel" });
        sendRealtimeEvent({ type: "output_audio_buffer.clear" });
        assistantAudioActive = false;
      }
      micTrack.enabled = true;
      $("voiceHint").textContent = "Preparing the microphone. Start speaking when the status changes to recording.";
      setVoiceStatus({ recording: "arming", note: "Warming the WebRTC mic track before clearing the input buffer." });

      setTimeout(() => {
        if (!dc || dc.readyState !== "open" || !micTrack) {
          isArmingAnswer = false;
          return;
        }
        sendRealtimeEvent({ type: "input_audio_buffer.clear" });
        answerStartedAt = Date.now();
        isArmingAnswer = false;
        isRecording = true;
        $("voiceHint").textContent = "Recording. Speak now; the page will stop after silence.";
        setVoiceStatus({
          recording: "started",
          auto: options.auto || false,
          mic_level_percent: lastMicPercent,
          note: "Hands-free mode is listening. Speak your answer; it will stop after silence."
        });
        markLatency("listening_started");
      }, 200);
    }

    function stopAnswer(options = {}) {
      if (currentProvider === "mock") {
        stopLocalRecognition();
        lastAnswerDurationSeconds = answerStartedAt ? Math.round((Date.now() - answerStartedAt) / 100) / 10 : null;
        isRecording = false;
        setStatus("Stopped. Review transcript, then submit.");
      } else {
        if (!isRecording) return options.auto ? null : setVoiceStatus("Not currently recording.");
        const durationMs = answerStartedAt ? Date.now() - answerStartedAt : 0;
        lastAnswerDurationSeconds = Math.round(durationMs / 100) / 10;
        isRecording = false;
        if (durationMs < MIN_RECORDING_MS) {
          awaitingTranscript = false;
          sendRealtimeEvent({ type: "input_audio_buffer.clear" });
          if (micTrack) micTrack.enabled = false;
          setVoiceStatus({
            recording: "too_short",
            duration_seconds: lastAnswerDurationSeconds,
            note: "Recording was too short, so the buffer was cleared instead of transcribed."
          });
          return;
        }
        awaitingTranscript = true;
        sendRealtimeEvent({ type: "input_audio_buffer.commit" });
        setTimeout(() => {
          if (micTrack) micTrack.enabled = false;
        }, 250);
        setVoiceStatus({
          recording: "stopped",
          audio: "committed",
          auto: options.auto || false,
          duration_seconds: lastAnswerDurationSeconds,
          note: "Waiting for transcript; review it before submitting."
        });
      }
    }

    async function submitAnswer(options = {}) {
      const sessionId = $("sessionId").value.trim();
      const transcript = $("transcript").value.trim();
      if (!transcript) {
        autoSubmitting = false;
        return setStatus("Transcript is empty. Record again or type the answer before submitting.");
      }
      if (currentProvider === "openai_realtime" && transcriptLooksInvalid(transcript)) {
        autoSubmitting = false;
        return setVoiceStatus({
          transcriptRejected: transcript,
          note: "This looks like a tiny/noisy fragment, not a real answer. Record again or type the transcript manually."
        });
      }
      if (currentProvider === "openai_realtime" && transcriptLooksHallucinatedForDuration(transcript)) {
        autoSubmitting = false;
        return setVoiceStatus({
          transcriptRejected: transcript,
          duration_seconds: lastAnswerDurationSeconds,
          note: "This transcript is too long for the captured audio duration, so it was not submitted."
        });
      }
      markLatency("final_transcript_submit", { via: voiceStream && voiceStream.readyState === WebSocket.OPEN ? "websocket" : "rest" });
      if (sendVoiceStream({
        type: "transcript_final",
        transcript_text: transcript,
        audio_duration_seconds: lastAnswerDurationSeconds
      })) {
        return;
      }
      const response = await fetch(`/interviews/${sessionId}/voice/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transcript_text: transcript,
          audio_duration_seconds: lastAnswerDurationSeconds
        })
      });
      const data = await response.json();
      markLatency("backend_response_received", { via: "rest" });
      autoSubmitting = false;
      if (!response.ok) return setStatus(data);
      applyVoiceTurnResult(data);
    }

    function applyVoiceTurnResult(data) {
      currentQuestion = data.next_question_text || "";
      $("questionText").textContent = currentQuestion || "Interview completed or no next question.";
      $("transcript").value = "";
      isRecording = false;
      awaitingTranscript = false;
      pendingTranscriptItemId = null;
      setStatus(data);
      if (currentQuestion) {
        markLatency("next_tts_starting");
        sendRealtimeSpeak(currentQuestion);
      } else if (data.state && data.state.status === "completed") {
        disconnectVoice({ ended: true, keepStatus: true });
        setStatus({ ui: "Interview completed", state: data.state });
      }
    }

    $("endInterview").onclick = async () => {
      const sessionId = $("sessionId").value.trim();
      if (!sessionId) {
        disconnectVoice({ ended: true, keepStatus: true });
        return setStatus("No active interview session.");
      }
      const response = await fetch(`/interviews/${sessionId}/end`, { method: "POST" });
      const data = await response.json();
      disconnectVoice({ ended: true, keepStatus: true });
      setStatus(data);
    };

    loadProviderStatus();
    loadAudioInputDevices();
    updateControls();
