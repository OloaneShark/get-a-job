
function copyPrompt(event) {
    const prompt = document.getElementById("manualPrompt");

    if (!prompt) {
        return;
    }

    navigator.clipboard.writeText(prompt.value)
        .then(() => {
            const button = event.target;

            const originalText = button.innerText;

            button.innerText = "✅ Copied!";

            setTimeout(() => {
                button.innerText = originalText;
            }, 2000);
        })
        .catch(() => {
            alert("Unable to copy the prompt.");
        });
}
