import { PolarH10 } from "https://unpkg.com/polar-h10@1.0.1/dist/esm/index.js";

const PMD_SERVICE_ID = "fb005c80-02e7-f387-1cad-8acd2d8df0c8";

const statusElem = document.getElementById('status');
const deviceNameElem = document.getElementById('deviceName');
const uploadKeyElem = document.getElementById('uploadKey');
const sampleCountElem = document.getElementById('sampleCount');
const connectBtn = document.getElementById('connectBtn');
const disconnectBtn = document.getElementById('disconnectBtn');
const clearBtn = document.getElementById('clearBtn');
const exportBtn = document.getElementById('exportBtn');
const deviceName_copyBtn = document.getElementById('deviceName_copyBtn');
const uploadKey_copyBtn = document.getElementById('uploadKey_copyBtn');

let polarH10;
let records = [];
let ecgCount = 0;
let accCount = 0;

function setStatus(text) {
  statusElem.textContent = text;
}
function setEnabled(ids, enabled) {
  ids.forEach(id => document.getElementById(id).disabled = !enabled);
}

function newUploadSession() {
  return fetch('/api/new-upload-key', { method: 'POST' })
    .then((response) => {
      if (!response.ok) {
        throw new Error('Failed to obtain upload key: ' + response.status);
      }
      return response.json();
    })
    .then((data) => {
      if (!data || typeof data.upload_key !== 'string' || data.upload_key.length === 0) {
        throw new Error('Malformed upload key response');
      }
      return { key: data.upload_key, name: data.name };
    })
    .catch((error) => {
      console.error('Unable to initialize upload session', error);
      throw error;
    });
}

function uploadRecords(entries, session) {
  if (entries.length === 0) {
    return;
  }
  const body = entries.map(JSON.stringify).join('\n');
  if (!session.key) {
    console.error('No upload key available for upload');
    return;
  }

  const url = '/api/upload?upload_key=' + encodeURIComponent(session.key);

  return fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-ndjson'
    },
    body: body
  })
    .then((response) => {
      if (!response.ok) {
        throw new Error('Unexpected response status ' + response.status);
      }
      return response.text().catch(() => '');
    })
    .then(() => {
      this.markRecordsUploaded(entries);
    })
    .catch((error) => {
      console.error('Failed to upload records', error);
    });
}

function onData(data) {
  try {
    let samples = data.samples;
    if (data.type === "ACC") {
      const samples_x = [];
      const samples_y = [];
      const samples_z = [];
      for (let i = 0; i < data.samples.length; i += 3) {
        samples_x.push(-data.samples[i]);
        samples_y.push(-data.samples[i + 1]);
        samples_z.push(data.samples[i + 2]);
      }
      samples = {x: samples_x, y: samples_y, z: samples_z};
    } else if (data.type === "ECG") {
      samples = Array.from(data.samples);
    }
    records.push({
      type: data.type,
      epoch_ms: Date.now(),
      ts_ms: data.sample_timestamp_ms,
      prev_ts_ms: data.prev_sample_timestamp_ms,
      samples: samples, // milliG for ACC, µV for ECG
    });
    if (data.type === "ACC") {
      accCount ++;
    } else if (data.type === "ECG") {
      ecgCount ++;
    }
    sampleCountElem.innerHTML = `${ecgCount} ECG<br/>${accCount} ACC<br/>${ecgCount + accCount} total`;
  } catch (err) {
    console.error(err);
    setStatus('Error while getting data: ' + (err?.message || err));
  }
}

async function connect() {
  try {
    setStatus('Requesting device…');

    const deviceOptions = {
      filters: [
        { namePrefix: "Polar H10" },
      ],
      optionalServices: [
        "battery_service",
        "fb005c80-02e7-f387-1cad-8acd2d8df0c8",
      ],
    };

    const device = await navigator.bluetooth.requestDevice(deviceOptions);
    device.addEventListener('gattserverdisconnected', onDisconnected);

    deviceNameElem.textContent = device.name || '(Unnamed)';
    setStatus('Connecting…');
    polarH10 = new PolarH10(device);
    setStatus('Connecting: requested services.');
    polarH10.addEventListener("ECG", onData);
    polarH10.addEventListener("ACC", onData);
    await polarH10.init();
    setStatus('Connecting: initialized.');
    await polarH10.startECG(130);
    await polarH10.startACC(4, 200);
    setStatus('Connected: started ECG and accel. data stream.');
    setEnabled(['connectBtn'], false);
    setEnabled(['disconnectBtn'], true);
    setInterval(async () => {
      const ourRecords = records;
      records = [];
      await uploadRecords(ourRecords, uploadSession);
      setStatus(`Uploaded up to ${records.length} records.`);
    }, 1000);
  } catch (err) {
    console.error(err);
    setStatus('Error: ' + (err?.message || err));
    cleanupPartial();
  }
}

async function disconnect() {
  try {
    if (hrChar) {
      hrChar.removeEventListener('characteristicvaluechanged', onHeartRateMeasurement);
      try { await hrChar.stopNotifications(); } catch (_) {}
    }
    if (device?.gatt?.connected) {
      device.gatt.disconnect();
    }
  } finally {
    setStatus('Disconnected');
    setEnabled(['connectBtn'], true);
    setEnabled(['disconnectBtn'], false);
  }
}

function onDisconnected() {
  setStatus('Disconnected');
  setEnabled(['connectBtn'], true);
  setEnabled(['disconnectBtn'], false);
}

function cleanupPartial() {
  hrChar = null; server = null;
  if (device && device.gatt && device.gatt.connected) {
    try { device.gatt.disconnect(); } catch (_) {}
  }
  setEnabled(['connectBtn'], true);
  setEnabled(['disconnectBtn'], false);
}

connectBtn.addEventListener('click', async () => {
  if (!('bluetooth' in navigator)) {
    setStatus('Web Bluetooth not supported in this browser.');
    return;
  }
  await connect();
});

disconnectBtn.addEventListener('click', disconnect);

deviceName_copyBtn.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(deviceNameElem.textContent);
    setStatus('Copied device name to clipboard.');
  } catch (e) {
    setStatus('Failed to copy.');
  }
});
uploadKey_copyBtn.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(uploadKeyElem.textContent);
    setStatus('Copied upload key to clipboard.');
  } catch (e) {
    setStatus('Failed to copy.');
  }
});

const uploadSession = await newUploadSession();
uploadKeyElem.textContent = uploadSession.name;
