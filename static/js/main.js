document.addEventListener('DOMContentLoaded', () => {
    const chatToggleBtn = document.getElementById('chatToggleBtn');
    const chatCloseBtn = document.getElementById('chatCloseBtn');
    const chatBox = document.getElementById('chatBox');
    const chatForm = document.getElementById('chatForm');
    const chatInput = document.getElementById('chatInput');
    const chatMessages = document.getElementById('chatMessages');

    if (!chatToggleBtn || !chatBox || !chatForm) return;

    const appendMessage = (text, sender, time) => {
        const bubble = document.createElement('div');
        const outgoing = sender !== 'Администратор';
        bubble.className = `chat-bubble ${outgoing ? 'outgoing' : 'incoming'}`;
        bubble.textContent = `${sender}: ${text}${time ? ' · ' + time : ''}`;
        chatMessages.appendChild(bubble);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    };

    const loadMessages = async () => {
        try {
            const response = await fetch('/api/chat');
            if (!response.ok) return;
            const messages = await response.json();
            chatMessages.replaceChildren();
            if (!messages.length) {
                const welcome = document.createElement('div');
                welcome.className = 'chat-bubble incoming';
                welcome.textContent = 'Здравствуйте! Напишите свой вопрос администрации МедХаб.';
                chatMessages.appendChild(welcome);
            }
            messages.forEach(message => appendMessage(message.text, message.sender, message.time));
        } catch (error) { console.error('Не удалось загрузить историю чата:', error); }
    };

    chatToggleBtn.addEventListener('click', () => {
        chatBox.style.display = chatBox.style.display === 'flex' ? 'none' : 'flex';
        if (chatBox.style.display === 'flex') loadMessages();
    });
    chatCloseBtn?.addEventListener('click', () => { chatBox.style.display = 'none'; });

    chatForm.addEventListener('submit', async event => {
        event.preventDefault();
        const text = chatInput.value.trim();
        if (!text) return;
        try {
            const response = await fetch('/api/chat', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({text})
            });
            if (!response.ok) throw new Error('Chat request rejected');
            chatInput.value = '';
            await loadMessages();
        } catch (error) {
            console.error('Ошибка отправки чата:', error);
            alert('Не удалось отправить сообщение. Попробуйте ещё раз.');
        }
    });
});
