// A simple client for the Messenger backend (plain JavaScript, no build step).
// It only calls the backend's REST API and its two WebSocket endpoints.

let currentUser = null;   // the logged in user (object) or null
let conversations = [];   // the list shown in the sidebar
let activeId = null;      // id of the conversation that is open
let messages = [];        // messages of the open conversation
let chatSocket = null;    // websocket of the open conversation
let notifySocket = null;  // one websocket for "you got a new message" events
let unread = {};          // conversation id -> number of unread messages
let audioContext = null;  // used to play the notification sound
let lastSentMessage = null; // tracks the last message we sent so we do not play duplicate sounds on echoed websocket events
let previewUrl = '';      // temporary url of the profile picture the user just chose

const MAX_PICTURE_SIZE = 2 * 1024 * 1024; // 2 MB, the same limit as the backend

const $ = (id) => document.getElementById(id);


// ---------- helpers ----------

// Django sends a "csrftoken" cookie. For POST/DELETE requests we send the same value
// back in the X-CSRFToken header, otherwise Django rejects the request.
function getCookie(name) {
  for (const part of document.cookie.split('; ')) {
    const [key, ...rest] = part.split('=');
    if (key === name) return decodeURIComponent(rest.join('='));
  }
  return '';
}

// Errors from the API look like {detail: "..."} or {content: ["..."]}
function errorText(data) {
  if (!data) return 'Something went wrong. Please try again.';
  if (data.detail) return data.detail;
  const first = Object.values(data)[0];
  return Array.isArray(first) ? first[0] : String(first);
}

// One function for every API call. "body" can be an object (sent as JSON)
// or FormData (used for the profile picture upload).
async function api(url, method = 'GET', body = null) {
  const options = {
    method,
    credentials: 'same-origin', // send the login cookie
    headers: { 'X-CSRFToken': getCookie('csrftoken') },
  };

  if (body instanceof FormData) {
    options.body = body; // the browser sets the content type itself
  } else if (body) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }

  const response = await fetch(url, options);

  let data = null;
  if (response.status !== 204) { // 204 = no content
    try {
      data = await response.json();
    } catch (error) {
      data = null;
    }
  }

  if (!response.ok) {
    const error = new Error(errorText(data));
    error.status = response.status;
    throw error;
  }
  return data;
}

function showMessage(elementId, type, text) {
  const box = $(elementId);
  box.textContent = text;
  box.className = text ? `message ${type}` : 'message hidden';
}

// The round picture, or the first letter of the name when there is no picture.
// textContent / img.src are used (never innerHTML), so names can not run as code (XSS).
function makeAvatar(name, picture, small) {
  const box = document.createElement('span');
  box.className = small ? 'avatar small' : 'avatar';
  const letter = name ? name[0].toUpperCase() : '?';

  if (picture) {
    const image = document.createElement('img');
    image.alt = '';
    image.src = picture;
    image.onerror = () => { box.textContent = letter; }; // picture file is missing
    box.appendChild(image);
  } else {
    box.textContent = letter;
  }
  return box;
}


// ---------- websocket helper (connects again when the connection drops) ----------

function openSocket(path, handlers) {
  let socket = null;
  let stopped = false;
  let attempts = 0;
  let timer = null;

  function connect() {
    // https pages must use wss:// (secure), normal pages use ws://
    const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
    socket = new WebSocket(`${scheme}://${window.location.host}${path}`);

    socket.onopen = () => {
      attempts = 0;
      if (handlers.onOpen) handlers.onOpen();
    };

    socket.onmessage = (event) => handlers.onMessage(JSON.parse(event.data));

    socket.onclose = (event) => {
      if (handlers.onClose) handlers.onClose();

      // 4401 / 4403 = the server refused us on purpose, so do not try again
      if (stopped || event.code === 4401 || event.code === 4403) return;

      // wait 1s, 2s, 4s ... (maximum 10s) and connect again
      const delay = Math.min(1000 * 2 ** attempts, 10000);
      attempts += 1;
      timer = setTimeout(connect, delay);
    };
  }

  connect();

  return {
    // returns false when the socket is not connected
    send(data) {
      if (!socket || socket.readyState !== WebSocket.OPEN) return false;
      socket.send(JSON.stringify(data));
      return true;
    },
    close() {
      stopped = true;
      clearTimeout(timer);
      if (socket) socket.close();
    },
  };
}


// ---------- notifications: sound + desktop notification + unread count ----------

// Browsers only allow sound after the user has clicked something on the page,
// so we create / resume the audio engine on every valid user interaction.
function unlockAudio() {
  try {
    if (!audioContext) {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioContext.state === 'suspended') audioContext.resume();
  } catch (error) {
    audioContext = null;
  }
}
document.addEventListener('pointerdown', unlockAudio);
document.addEventListener('keydown', unlockAudio);

// A short "ding-dong" made with the browser's audio API, so no sound file is needed.
function playSound() {
  unlockAudio();
  if (!audioContext) return;

  try {
    const now = audioContext.currentTime;
    const oscillator = audioContext.createOscillator();
    const volume = audioContext.createGain();

    oscillator.type = 'sine';
    oscillator.frequency.setValueAtTime(880, now);
    oscillator.frequency.setValueAtTime(1175, now + 0.15);

    volume.gain.setValueAtTime(0.0001, now);
    volume.gain.exponentialRampToValueAtTime(0.25, now + 0.02);
    volume.gain.exponentialRampToValueAtTime(0.0001, now + 0.45);

    oscillator.connect(volume);
    volume.connect(audioContext.destination);
    oscillator.start(now);
    oscillator.stop(now + 0.5);
  } catch (error) {
    console.error('Could not play the sound', error);
  }
}

function soundIsOn() {
  return true;
}

function showDesktopNotification(title, body, conversationId) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;

  try {
    const note = new Notification(title, { body });
    note.onclick = () => {
      window.focus();
      if (conversationId) openConversation(conversationId);
      note.close();
    };
  } catch (error) {
    console.error('Could not show the notification', error);
  }
}

// The tab title shows the number of unread messages, for example "(3) Messenger"
function updateTitle() {
  const total = Object.values(unread).reduce((sum, count) => sum + count, 0);
  document.title = total > 0 ? `(${total}) Messenger` : 'Messenger';
}

// Called when the server tells us that somebody sent us a message
function handleNewMessage(message) {
  const lookingAtIt = message.conversation === activeId && !document.hidden;

  // Ignore the echoed message we just sent so the sound is not duplicated.
  const isOurOwnEcho =
    lastSentMessage &&
    message.sender === currentUser?.id &&
    message.conversation === lastSentMessage.conversation &&
    message.content === lastSentMessage.content &&
    Date.now() - lastSentMessage.timestamp < 5000;

  if (!lookingAtIt) {
    unread[message.conversation] = (unread[message.conversation] || 0) + 1;
    updateTitle();
    showDesktopNotification(`New message from ${message.sender_username}`, message.content, message.conversation);
  }

  if (!isOurOwnEcho && soundIsOn()) {
    playSound();
  }

  loadConversations();
}

// Shows the "turn on desktop notifications" button only when the browser still has to ask
function updateNotifyButton() {
  const hint = $('notify-hint');

  if (!('Notification' in window)) {
    $('notify-button').classList.add('hidden');
    hint.textContent = 'This browser does not support desktop notifications.';
    hint.classList.remove('hidden');
    return;
  }

  $('notify-button').classList.toggle('hidden', Notification.permission !== 'default');

  if (Notification.permission === 'denied') {
    hint.textContent = 'Desktop notifications are blocked. Allow them in the browser site settings.';
    hint.classList.remove('hidden');
  } else {
    hint.classList.add('hidden');
  }
}

$('notify-button').addEventListener('click', async () => {
  await Notification.requestPermission();
  updateNotifyButton();
});


// when the user comes back to the tab, the open chat is read
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && activeId) {
    unread[activeId] = 0;
    updateTitle();
    renderConversations();
  }
});


// ---------- login, register, password reset ----------

const authForms = ['login-form', 'register-form', 'forgot-form', 'reset-form'];

function showAuthForm(formId) {
  authForms.forEach((id) => $(id).classList.toggle('hidden', id !== formId));
  showMessage('auth-message', '', '');
}

document.querySelectorAll('[data-show]').forEach((link) => {
  link.addEventListener('click', (event) => {
    event.preventDefault();
    showAuthForm(link.dataset.show);
  });
});

$('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    const data = await api('/api/auth/login/', 'POST', {
      username: $('login-username').value,
      password: $('login-password').value,
    });
    $('login-password').value = '';
    startChat(data.user);
  } catch (error) {
    showMessage('auth-message', 'error', error.message);
  }
});

$('register-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    await api('/api/auth/register/', 'POST', {
      username: $('register-username').value,
      email: $('register-email').value,
      password: $('register-password').value,
      confirm_password: $('register-confirm').value,
      unique_id: $('register-unique-id').value,
    });
    event.target.reset();
    showAuthForm('login-form');
    showMessage('auth-message', 'info', 'Account created. Please sign in.');
  } catch (error) {
    showMessage('auth-message', 'error', error.message);
  }
});

$('forgot-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    const data = await api('/api/auth/password-reset/', 'POST', { email: $('forgot-email').value });
    showMessage('auth-message', 'info', data.detail);

    if (data.reset_link) {
      const link = document.createElement('a');
      link.href = data.reset_link;
      link.textContent = ' Open the reset page';
      $('auth-message').appendChild(link);
    }
  } catch (error) {
    showMessage('auth-message', 'error', error.message);
  }
});

$('reset-form').addEventListener('submit', async (event) => {
  event.preventDefault();

  if ($('reset-password').value !== $('reset-confirm').value) {
    showMessage('auth-message', 'error', 'Passwords do not match.');
    return;
  }

  const match = window.location.pathname.match(/^\/reset-password\/([^/]+)\/([^/]+)\/?$/);
  if (!match) {
    showMessage('auth-message', 'error', 'This reset link is not valid.');
    return;
  }

  try {
    await api('/api/auth/password-reset-confirm/', 'POST', {
      uid: match[1],
      token: match[2],
      new_password: $('reset-password').value,
    });
    event.target.reset();
    window.history.replaceState(null, '', '/');
    showAuthForm('login-form');
    showMessage('auth-message', 'info', 'Password changed. You can sign in now.');
  } catch (error) {
    showMessage('auth-message', 'error', error.message);
  }
});



// ---------- my profile (name, bio, picture) ----------

function renderMe() {
  $('me-avatar-box').replaceChildren(makeAvatar(currentUser.username, currentUser.profile_picture, false));
  $('me-name').textContent = currentUser.username;
  $('me-id').textContent = currentUser.unique_id;
  $('me-bio').textContent = currentUser.bio || '';
}

function showPreview(picture) {
  $('profile-preview').replaceChildren(makeAvatar(currentUser.username, picture, false));
}

// puts the saved values into the profile form
function fillProfileForm() {
  if (previewUrl) {
    URL.revokeObjectURL(previewUrl);
    previewUrl = '';
  }
  $('profile-name').value = currentUser.username;
  $('profile-bio').value = currentUser.bio || '';
  $('profile-picture').value = '';
  showPreview(currentUser.profile_picture);
  showMessage('profile-message', '', '');
}

$('profile-toggle').addEventListener('click', () => {
  const opening = $('profile-form').classList.contains('hidden');
  $('profile-form').classList.toggle('hidden', !opening);
  $('profile-toggle').textContent = opening ? 'Close profile' : 'Edit profile';
  if (opening) fillProfileForm();
});

// show a preview of the chosen picture before saving
$('profile-picture').addEventListener('change', (event) => {
  const file = event.target.files[0];

  if (previewUrl) {
    URL.revokeObjectURL(previewUrl);
    previewUrl = '';
  }
  if (!file) {
    showPreview(currentUser.profile_picture);
    return;
  }

  // quick checks in the browser (the server checks again)
  let problem = '';
  if (!file.type.startsWith('image/')) problem = 'Please choose an image file.';
  else if (file.size > MAX_PICTURE_SIZE) problem = 'Image is too big. Maximum size is 2 MB.';

  if (problem) {
    event.target.value = '';
    showPreview(currentUser.profile_picture);
    showMessage('profile-message', 'error', problem);
    return;
  }

  showMessage('profile-message', '', '');
  previewUrl = URL.createObjectURL(file);
  showPreview(previewUrl);
});

$('profile-form').addEventListener('submit', async (event) => {
  event.preventDefault();

  // FormData is needed because we may upload a file
  const formData = new FormData();
  formData.append('username', $('profile-name').value.trim());
  formData.append('bio', $('profile-bio').value);
  const file = $('profile-picture').files[0];
  if (file) formData.append('profile_picture', file);

  try {
    const data = await api('/api/auth/profile/', 'POST', formData);
    currentUser = data.user;
    renderMe();
    fillProfileForm();
    showMessage('profile-message', 'info', 'Profile saved.');
  } catch (error) {
    showMessage('profile-message', 'error', error.message);
  }
});


// ---------- chat page ----------

function startChat(user) {
  currentUser = user;
  renderMe();
  updateNotifyButton();

  $('auth-screen').classList.add('hidden');
  $('chat-screen').classList.remove('hidden');

  loadConversations();

  // one websocket for the whole page: the server pushes "new message" events here
  notifySocket = openSocket('/ws/notifications/', {
    onMessage: (payload) => {
      if (payload.type === 'notification') handleNewMessage(payload.message);
    },
  });
}

function showLoginScreen() {
  currentUser = null;
  conversations = [];
  activeId = null;
  messages = [];
  unread = {};
  if (chatSocket) chatSocket.close();
  if (notifySocket) notifySocket.close();
  chatSocket = null;
  notifySocket = null;

  $('profile-form').classList.add('hidden');
  $('profile-toggle').textContent = 'Edit profile';
  $('chat-screen').classList.add('hidden');
  $('auth-screen').classList.remove('hidden');
  showAuthForm('login-form');
  updateTitle();
  renderChat();
}

async function loadConversations() {
  try {
    conversations = await api('/api/conversations/');
    renderConversations();
    renderChat();
  } catch (error) {
    // the login expired, go back to the login page
    if (error.status === 401 || error.status === 403) showLoginScreen();
  }
}

function renderConversations() {
  const list = $('conversation-list');
  list.replaceChildren();

  if (conversations.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = 'No conversations yet.';
    list.appendChild(empty);
    return;
  }

  conversations.forEach((conversation) => {
    const row = document.createElement('div');
    row.className = 'conversation-row';

    const open = document.createElement('button');
    open.type = 'button';
    open.className = conversation.id === activeId ? 'conversation active' : 'conversation';

    const text = document.createElement('span');
    text.className = 'conversation-text';
    const name = document.createElement('strong');
    name.textContent = conversation.participant;
    const last = document.createElement('small');
    last.textContent = conversation.last_message;
    text.append(name, last);

    open.append(makeAvatar(conversation.participant, conversation.participant_picture, true), text);

    // the red number of unread messages
    if (unread[conversation.id] > 0) {
      const badge = document.createElement('span');
      badge.className = 'badge';
      badge.textContent = unread[conversation.id];
      open.appendChild(badge);
    }
    open.addEventListener('click', () => openConversation(conversation.id));

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'delete-conversation';
    remove.title = 'Delete conversation';
    remove.textContent = '\u00d7';
    remove.addEventListener('click', () => deleteConversation(conversation.id));

    row.append(open, remove);
    list.appendChild(row);
  });
}

function openConversation(conversationId) {
  if (chatSocket) chatSocket.close();

  activeId = conversationId;
  messages = [];
  unread[conversationId] = 0;
  updateTitle();
  renderConversations();
  renderChat();
  loadMessages(conversationId);

  let openedBefore = false;
  chatSocket = openSocket(`/ws/conversations/${conversationId}/`, {
    onOpen: () => {
      $('chat-status').textContent = 'Live';
      // after a reconnect, load the messages that arrived while we were offline
      if (openedBefore) loadMessages(conversationId);
      openedBefore = true;
    },
    onClose: () => {
      $('chat-status').textContent = 'Connecting... (messages are sent over HTTP for now)';
    },
    onMessage: (payload) => {
      if (payload.type === 'message' && payload.message.conversation === activeId) {
        addMessages([payload.message]);
      }
      if (payload.type === 'error') {
        $('chat-status').textContent = payload.detail;
      }
    },
  });
}

async function loadMessages(conversationId) {
  try {
    const oldMessages = await api(`/api/conversations/${conversationId}/messages/`);
    if (conversationId === activeId) addMessages(oldMessages);
  } catch (error) {
    $('chat-status').textContent = error.message;
  }
}

// A message can arrive twice (websocket + http), so we keep one copy per id
function addMessages(newMessages) {
  const byId = new Map(messages.map((message) => [message.id, message]));
  newMessages.forEach((message) => byId.set(message.id, message));
  messages = [...byId.values()].sort((a, b) => a.id - b.id);
  renderChat();
}

function renderChat() {
  const conversation = conversations.find((item) => item.id === activeId);

  $('chat-title').textContent = conversation ? conversation.participant : 'Select a conversation';
  $('message-input').disabled = !conversation;
  $('send-button').disabled = !conversation;
  $('chat-avatar-box').replaceChildren();
  if (conversation) {
    $('chat-avatar-box').appendChild(makeAvatar(conversation.participant, conversation.participant_picture, true));
  }

  const box = $('messages');
  box.replaceChildren();

  if (!conversation) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = 'Pick a conversation on the left.';
    box.appendChild(empty);
    $('chat-status').textContent = '';
    return;
  }

  messages.forEach((message) => {
    const bubble = document.createElement('div');
    bubble.className = message.sender === currentUser.id ? 'bubble mine' : 'bubble';
    bubble.textContent = message.content;

    const time = document.createElement('time');
    time.textContent = new Date(message.created_at).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });
    bubble.appendChild(time);
    box.appendChild(bubble);
  });
  box.scrollTop = box.scrollHeight;
}

$('add-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const uniqueId = $('add-unique-id').value.trim();
  if (!uniqueId) return;

  try {
    const data = await api('/api/conversations/add/', 'POST', { unique_id: uniqueId });
    $('add-unique-id').value = '';
    showMessage('add-message', 'info', data.created ? 'User added!' : 'You already have a chat with this user.');
    await loadConversations();
    openConversation(data.conversation.id);
  } catch (error) {
    showMessage('add-message', 'error', error.message);
  }
});

async function deleteConversation(conversationId) {
  if (!window.confirm('Delete this conversation for everyone in it?')) return;

  try {
    await api(`/api/conversations/${conversationId}/`, 'DELETE');
    if (conversationId === activeId) {
      if (chatSocket) chatSocket.close();
      chatSocket = null;
      activeId = null;
      messages = [];
    }
    delete unread[conversationId];
    updateTitle();
    await loadConversations();
  } catch (error) {
    window.alert(error.message);
  }
}

$('message-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const content = $('message-input').value.trim();
  if (!content || !activeId) return;

  lastSentMessage = {
    content,
    conversation: activeId,
    timestamp: Date.now(),
  };

  // First choice: the websocket (instant). The server saves the message and sends it
  // back to everybody in the conversation, including us, so we do not add it here.
  if (chatSocket && chatSocket.send({ type: 'message', content })) {
    $('message-input').value = '';
    if (soundIsOn()) playSound();
    return;
  }

  // The websocket is not connected, so use a normal HTTP request instead
  try {
    const saved = await api(`/api/conversations/${activeId}/messages/`, 'POST', { content });
    addMessages([saved]);
    $('message-input').value = '';
    if (soundIsOn()) playSound();
    loadConversations();
  } catch (error) {
    $('chat-status').textContent = error.message;
  }
});

$('logout-button').addEventListener('click', async () => {
  try {
    await api('/api/auth/logout/', 'POST', {});
  } catch (error) {
    console.error('Logout failed', error);
  }
  showLoginScreen();
});


// ---------- start ----------

async function start() {
  try {
    const data = await api('/api/auth/me/'); // is there a valid login cookie?
    if (data.user) {
      startChat(data.user);
      return;
    }
  } catch (error) {
    console.error('Could not reach the server', error);
  }

  $('auth-screen').classList.remove('hidden');
  if (window.location.pathname.startsWith('/reset-password/')) {
    showAuthForm('reset-form');
  } else {
    showAuthForm('login-form');
  }
}

start();
