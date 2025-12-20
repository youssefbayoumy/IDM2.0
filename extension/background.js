const SERVER_URL = "http://127.0.0.1:6800/add";

chrome.downloads.onCreated.addListener((downloadItem) => {
  // Ignore downloads if they are already handled or if user paused
  if (downloadItem.state !== "in_progress") return;

  // Simple heuristic: Only intercept "large" files or specific types?
  // For now, intercept everything except those started by the extension itself?
  // Actually, capturing ALL downloads might be annoying if the server is off.
  // Ideally, we check if server is up first.

  // We can't cancel immediately in onCreated in V3 easily without `chrome.downloads.cancel`
  // But reliable interception usually involves sending to server, then cancelling browser download if successful.

  // NOTE: To avoid infinite loop, we should check if this download is initiated by us?
  // But we are sending URL to python app, which downloads it. Browser download is SEPARATE.
  // So if we cancel browser download, it's fine.

  // Let's check status of our server
  fetch("http://127.0.0.1:6800/test")
    .then(response => {
      if (response.ok) {
        // Server is up. Send download task.
        sendToIDM(downloadItem);
      }
    })
    .catch(err => {
      console.log("IDM Server not running, letting browser handle it.");
    });
});

function sendToIDM(item) {
  // Check if it's a blob URI
  if (item.url.startsWith('blob:')) {
    console.log("Processing blob URI:", item.url);
    fetch(item.url)
      .then(r => r.blob())
      .then(blob => {
        const reader = new FileReader();
        reader.onloadend = () => {
          const dataUrl = reader.result;
          // Send as data URI
          const payload = {
            url: dataUrl,
            filename: item.filename,
            headers: {
              "User-Agent": navigator.userAgent,
              "Referer": item.referrer
            }
          };
          postToIDM(payload, item.id);
        };
        reader.readAsDataURL(blob);
      })
      .catch(err => console.error("Failed to process blob:", err));
    return;
  }

  // Get cookies for normal URLs
  // Get cookies using both URL and Referrer to ensure we capture auth tokens
  Promise.all([getCookies(item.url), getCookies(item.referrer)])
    .then(([cookiesUrl, cookiesRef]) => {
      const cookieMap = new Map();
      // Prioritize URL cookies, but fill with Referrer cookies if missing?
      // Actually, usually we just want ALL valid cookies.
      // If there's a conflict, URL cookies should probably prevail if they exist.
      // But typically they are complementary or identical.

      if (cookiesRef) cookiesRef.forEach(c => cookieMap.set(c.name, c.value));
      if (cookiesUrl) cookiesUrl.forEach(c => cookieMap.set(c.name, c.value));

      const cookieStrings = [];
      cookieMap.forEach((value, name) => {
        cookieStrings.push(`${name}=${value}`);
      });
      const cookieString = cookieStrings.join("; ");

      console.log(`Sending download to IDM: ${item.url} with ${cookieStrings.length} cookies.`);

      const payload = {
        url: item.url,
        filename: item.filename,
        headers: {
          "User-Agent": navigator.userAgent,
          "Referer": item.referrer,
          "Cookie": cookieString
        }
      };

      postToIDM(payload, item.id);
    });
}

function postToIDM(payload, downloadId) {
  fetch(SERVER_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  })
    .then(res => res.json())
    .then(data => {
      if (data.status === "added" && downloadId > 0) {
        // Cancel browser download
        chrome.downloads.cancel(downloadId, () => {
          if (chrome.runtime.lastError) {
            console.log("Could not cancel download (might be context menu or already done):", chrome.runtime.lastError);
          } else {
            console.log("Download cancelled in browser and sent to IDM.");
          }
        });
      }
    })
    .catch(err => console.error("Failed to send to IDM:", err));
}

// Context Menu
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "download-with-idm",
    title: "Download with IDM Clone",
    contexts: ["link", "image", "video", "audio"]
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "download-with-idm") {
    const url = info.linkUrl || info.srcUrl;
    if (url) {
      const fakeItem = { url: url, filename: "", referrer: info.pageUrl, id: -1 }; // -1 id won't work for cancel, but loop above handles new downloads.
      // But for context menu, we just send directly.
      // We don't have a browser download ID to cancel here.
      sendToIDM_ContextMenu(fakeItem);
    }
  }
});

function sendToIDM_ContextMenu(item) {
  // Check if it's a blob URI
  if (item.url.startsWith('blob:')) {
    console.log("Context menu processing blob URI:", item.url);
    fetch(item.url)
      .then(r => r.blob())
      .then(blob => {
        const reader = new FileReader();
        reader.onloadend = () => {
          const dataUrl = reader.result;
          const payload = {
            url: dataUrl,
            filename: "",
            headers: {
              "User-Agent": navigator.userAgent,
              "Referer": item.referrer
            }
          };
          postToIDM(payload, -1);
        };
        reader.readAsDataURL(blob);
      })
      .catch(err => console.error("Failed to process blob in context menu:", err));
    return;
  }

  // Use robust cookie fetching
  Promise.all([getCookies(item.url), getCookies(item.referrer)])
    .then(([cookiesUrl, cookiesRef]) => {
      const cookieMap = new Map();
      if (cookiesRef) cookiesRef.forEach(c => cookieMap.set(c.name, c.value));
      if (cookiesUrl) cookiesUrl.forEach(c => cookieMap.set(c.name, c.value));

      const cookieStrings = [];
      cookieMap.forEach((value, name) => {
        cookieStrings.push(`${name}=${value}`);
      });
      const cookieString = cookieStrings.join("; ");

      console.log(`Context menu sending to IDM: ${item.url} with ${cookieStrings.length} cookies.`);

      const payload = {
        url: item.url,
        filename: "",
        headers: {
          "User-Agent": navigator.userAgent,
          "Referer": item.referrer,
          "Cookie": cookieString
        }
      };

      postToIDM(payload, -1);
    });
}

function getCookies(url) {
  return new Promise(resolve => {
    if (!url || !url.startsWith('http')) {
      resolve([]);
      return;
    }
    chrome.cookies.getAll({ url }, (cookies) => {
      resolve(cookies || []);
    });
  });
}
