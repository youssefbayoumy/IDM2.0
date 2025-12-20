const statusDiv = document.getElementById("status");

fetch("http://127.0.0.1:6800/test")
    .then(res => {
        if (res.ok) {
            statusDiv.textContent = "Connected";
            statusDiv.className = "status online";
        } else {
            throw new Error("Err");
        }
    })
    .catch(() => {
        statusDiv.textContent = "Disconnected";
        statusDiv.className = "status offline";
    });
