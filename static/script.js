document.addEventListener("DOMContentLoaded", () => {
  console.log("DOM loaded, initializing vintage video chat...");
  new VintageVideoChat();
});

class VintageVideoChat {
  constructor() {
    this.socket = io();
    this.localVideo = document.getElementById("localVideo");
    this.remoteVideo = document.getElementById("remoteVideo");
    this.startBtn = document.getElementById("startBtn");
    this.nextBtn = document.getElementById("nextBtn");
    this.endBtn = document.getElementById("endBtn");
    this.status = document.getElementById("status");
    this.noUsersModal = document.getElementById("noUsersModal");
    this.tryAgainBtn = document.getElementById("tryAgainBtn");

    // NEW: Get the user count element
    this.userCountNumber = document.getElementById("userCountNumber");

    this.localStream = null;
    this.peerConnection = null;
    this.isConnecting = false;

    this.initializeEventListeners();
    this.initializeSocketEvents();
  }

  initializeEventListeners() {
    this.startBtn.addEventListener("click", () => this.startVideoChat());
    this.nextBtn.addEventListener("click", () => this.findNextStranger());
    this.endBtn.addEventListener("click", () => this.endChat(true));
    this.tryAgainBtn.addEventListener("click", () => this.hideNoUsersModalAndRetry());
  }

  initializeSocketEvents() {
    this.socket.on("connect", () => {
      console.log("Connected to server with SID:", this.socket.id);
      this.updateStatus('Click "Start Video Chat" to begin');
    });
    
    // NEW: Listen for the user count update
    this.socket.on('user_count_update', (data) => {
        console.log(`User count updated: ${data.count}`);
        this.userCountNumber.textContent = data.count;
    });

    // ... (the rest of your initializeSocketEvents function remains the same) ...

    this.socket.on("waiting_for_match", () => {
      this.updateStatus("Searching for a stranger...", true);
    });

    this.socket.on("match_found", (data) => {
      console.log("Match found:", data);
      if (this.isConnecting) return;
      this.isConnecting = true;
      this.updateStatus("Stranger found! Connecting...", true);
      this.createPeerConnection();
      this.makeOffer();
    });

    this.socket.on("offer", (data) => {
      console.log("Received offer");
      if (this.isConnecting) return;
      this.isConnecting = true;
      this.createPeerConnection();
      this.handleOffer(data);
    });

    this.socket.on("answer", (data) => {
      console.log("Received answer");
      this.handleAnswer(data);
    });

    this.socket.on("ice_candidate", (data) => {
      console.log("Received ICE candidate");
      this.handleIceCandidate(data);
    });

    this.socket.on("user_disconnected", () => {
      this.updateStatus("Stranger has disconnected. Find another?");
      this.endChat(false);
    });

    this.socket.on("chat_ended", () => {
      this.updateStatus("Chat ended. Find another stranger?");
      this.endChat(false);
    });
  }

  // ... (the rest of your script.js methods remain the same) ...
  async startVideoChat() {
    try {
      this.updateStatus("Accessing camera and microphone...", true);
      this.localStream = await navigator.mediaDevices.getUserMedia({
        video: { width: 400, height: 300 },
        audio: true,
      });
      this.localVideo.srcObject = this.localStream;

      this.startBtn.style.display = "none";
      this.nextBtn.style.display = "inline-block";
      this.endBtn.style.display = "inline-block";

      this.findStranger();
    } catch (error) {
      console.error("Error accessing media devices:", error);
      this.updateStatus("Error: Could not access camera. Please allow permissions.");
      this.resetToInitialState();
    }
  }

  findStranger() {
    this.updateStatus("Looking for a stranger...", true);
    this.socket.emit("find_stranger");
  }

  findNextStranger() {
    this.endChat(false); // End current connection without resetting fully
    this.findStranger();
  }

  endChat(userInitiated) {
    if (userInitiated) {
        this.socket.emit("end_chat");
    }
    this.endCurrentConnection();
    if (userInitiated) {
        this.resetToInitialState();
    } else {
        this.updateStatus('Click "Next Stranger" to find someone new.');
    }
  }
  
  endCurrentConnection() {
    if (this.peerConnection) {
      this.peerConnection.close();
      this.peerConnection = null;
    }
    this.remoteVideo.srcObject = null;
    this.isConnecting = false;
    this.updateStatus("Chat disconnected.", false);
  }

  resetToInitialState() {
    if (this.localStream) {
      this.localStream.getTracks().forEach((track) => track.stop());
      this.localStream = null;
    }

    this.localVideo.srcObject = null;
    this.remoteVideo.srcObject = null;

    this.startBtn.style.display = "inline-block";
    this.nextBtn.style.display = "none";
    this.endBtn.style.display = "none";

    this.updateStatus('Click "Start Video Chat" to begin');
  }

  createPeerConnection() {
    if (this.peerConnection) {
        console.log("Peer connection already exists.");
        return;
    }
    console.log("Creating new peer connection...");
    const configuration = {
      iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
    };
    this.peerConnection = new RTCPeerConnection(configuration);

    if (this.localStream) {
      this.localStream.getTracks().forEach((track) => {
        this.peerConnection.addTrack(track, this.localStream);
      });
    }

    this.peerConnection.ontrack = (event) => {
      console.log("Remote stream received");
      this.remoteVideo.srcObject = event.streams[0];
      this.isConnecting = false;
      this.updateStatus("Connected! Say hi!");
    };

    this.peerConnection.onicecandidate = (event) => {
      if (event.candidate) {
        this.socket.emit("ice_candidate", { candidate: event.candidate });
      }
    };

    this.peerConnection.onconnectionstatechange = () => {
      console.log("Connection state:", this.peerConnection.connectionState);
      if (this.peerConnection.connectionState === "failed" || this.peerConnection.connectionState === "disconnected") {
        this.endChat(false);
      }
    };
  }

  async makeOffer() {
    try {
      const offer = await this.peerConnection.createOffer();
      await this.peerConnection.setLocalDescription(offer);
      this.socket.emit("offer", { offer: offer });
    } catch (error) {
      console.error("Error creating offer:", error);
    }
  }

  async handleOffer(data) {
    try {
      await this.peerConnection.setRemoteDescription(new RTCSessionDescription(data.offer));
      const answer = await this.peerConnection.createAnswer();
      await this.peerConnection.setLocalDescription(answer);
      this.socket.emit("answer", { answer: answer });
    } catch (error) {
      console.error("Error handling offer:", error);
    }
  }

  async handleAnswer(data) {
    try {
      await this.peerConnection.setRemoteDescription(new RTCSessionDescription(data.answer));
    } catch (error) {
      console.error("Error handling answer:", error);
    }
  }

  async handleIceCandidate(data) {
    try {
      if(data.candidate) {
        await this.peerConnection.addIceCandidate(new RTCIceCandidate(data.candidate));
      }
    } catch (error) {
      console.error("Error handling ICE candidate:", error);
    }
  }

  updateStatus(message, showPulse = false) {
    this.status.innerHTML = `<p class="${showPulse ? "pulse" : ""}">${message}</p>`;
  }
  
  hideNoUsersModalAndRetry() {
    this.noUsersModal.style.display = 'none';
    this.findStranger();
  }
}