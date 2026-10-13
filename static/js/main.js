document.addEventListener('DOMContentLoaded', () => {
    const chatToggleBtn = document.getElementById('chatToggleBtn');
    const chatCloseBtn = document.getElementById('chatCloseBtn');
    const chatBox = document.getElementById('chatBox');
    const chatForm = document.getElementById('chatForm');
    const chatInput = document.getElementById('chatInput');
    const chatMessages = document.getElementById('chatMessages');

    if (chatToggleBtn && chatBox) {
        chatToggleBtn.addEventListener('click', () => {
            chatBox.style.display = (chatBox.style.display === 'flex') ? 'none' : 'flex';
        });

        chatCloseBtn.addEventListener('click', () => {
            chatBox.style.display = 'none';
        });

        chatForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const text = chatInput.value.trim();
            if (!text) return;

            appendMessage(text, 'outgoing');
            chatInput.value = '';

            try {
                await fetch('/api/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({text: text, sender: 'Посетитель'})
                });

                setTimeout(() => {
                    appendMessage('Спасибо за обращение! Передал ваш вопрос куратору направления. Мы ответим вам в течение 10 минут.', 'incoming');
                }, 1000);
            } catch (err) {
                console.error('Ошибка отправки чата:', err);
            }
        });
    }

    function appendMessage(text, type) {
        const bubble = document.createElement('div');
        bubble.className = `chat-bubble ${type}`;
        bubble.textContent = text;
        chatMessages.appendChild(bubble);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }
});