document.addEventListener('DOMContentLoaded', () => {
    setupEventsPage();
    loadEvents();
});

// --- 共用函式 ---
async function apiFetch(url, options = {}) {
    try {
        const response = await fetch(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            }
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'API 請求失敗');
        }
        return data;
    } catch (error) {
        console.error('API Fetch Error:', error);
        return { error: error.message };
    }
}

function setupEventsPage() {
    document.getElementById('status-filter').addEventListener('change', loadEvents);
    document.getElementById('add-event-btn').addEventListener('click', showAddEventModal);
    
    const modal = document.getElementById('event-modal');
    if (modal) {
        modal.querySelector('.close-btn').addEventListener('click', () => modal.style.display = 'none');
        window.addEventListener('click', (event) => {
            if (event.target === modal) {
                modal.style.display = 'none';
            }
        });
    }
}

async function loadEvents() {
    const status = document.getElementById('status-filter').value;
    try {
        const events = await apiFetch(`/api/events?status=${status}`);
        const tableBody = document.getElementById('events-table').querySelector('tbody');
        tableBody.innerHTML = '';

        if (events && events.length > 0) {
            events.forEach(event => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>#${event.id}</td>
                    <td>${event.event_title}</td>
                    <td>${event.severity}</td>
                    <td>${event.status}</td>
                    <td>${event.assigned_to || '未指派'}</td>
                    <td>${new Date(event.event_time).toLocaleString()}</td>
                    <td><button onclick="showEventDetails(${event.id})">檢視/處理</button></td>
                `;
                tableBody.appendChild(tr);
            });
        } else {
            tableBody.innerHTML = '<tr><td colspan="7">找不到符合條件的事件。</td></tr>';
        }
    } catch (error) {
        console.error('Load Events Error:', error);
        document.getElementById('events-table').querySelector('tbody').innerHTML = '<tr><td colspan="7">載入事件失敗。</td></tr>';
    }
}

function showAddEventModal() {
    const modalBody = document.getElementById('modal-body');
    modalBody.innerHTML = `
        <h3>手動建立新事件</h3>
        <form id="add-event-form" class="form-container">
            <div class="form-group"><label>事件標題:</label><input type="text" name="event_title" required></div>
            <div class="form-group"><label>初始描述:</label><textarea name="initial_description" rows="3"></textarea></div>
            <div class="form-group"><label>嚴重性:</label><select name="severity"><option value="low">低</option><option value="medium" selected>中</option><option value="high">高</option></select></div>
            <div class="form-group"><label>指派給:</label><input type="text" name="assigned_to" placeholder="人員姓名/部門"></div>
            <div class="form-group"><label>預計完成日:</label><input type="date" name="due_date"></div>
            <div class="form-group"><label>事件類型:</label><input type="text" name="event_type" placeholder="例如: 系統錯誤, 數據異常"></div>
            <div class="form-group"><label>影響範圍:</label><input type="text" name="impact_scope" placeholder="例如: 某部門, 某服務, 50位用戶"></div>
            <div class="form-group"><label>根本原因:</label><textarea name="root_cause" rows="3" placeholder="簡述事件的根本原因"></textarea></div>
            <button type="submit" class="primary">建立事件</button>
        </form>
    `;

    const form = document.getElementById('add-event-form');
    if (form) {
        form.addEventListener('submit', handleAddEvent);
    }

    document.getElementById('event-modal').style.display = 'block';
}

async function handleAddEvent(e) {
    e.preventDefault();
    const formData = new FormData(e.target);
    const payload = Object.fromEntries(formData.entries());
    if (!payload.event_title) {
        alert('請輸入事件標題');
        return;
    }
    // 新增的欄位
    payload.event_type = document.querySelector('#add-event-form input[name="event_type"]').value;
    payload.impact_scope = document.querySelector('#add-event-form input[name="impact_scope"]').value;
    payload.root_cause = document.querySelector('#add-event-form textarea[name="root_cause"]').value;

    console.log('Submitting payload:', payload);
    const result = await apiFetch('http://127.0.0.1:5001/api/events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    console.log('API Response:', result);
    if (result && result.success) {
        alert('事件已建立！');
        document.getElementById('event-modal').style.display = 'none';
        loadEvents();
    } else {
        console.error('Error details:', result);
        alert(result && result.error ? result.error : '建立事件失敗');
    }
}

async function showEventDetails(eventId) {
    try {
        const data = await apiFetch(`/api/events/${eventId}`);
        if (!data) return;

        const { event, actions } = data;
        const modalBody = document.getElementById('modal-body');

        let actionsHtml = '<h4>處理歷程</h4><div class="actions-list">';
        actions.forEach(action => {
            actionsHtml += `
                <div class="action-item">
                    <strong>${action.author}</strong> 在 ${new Date(action.created_at).toLocaleString()} 新增了一筆 <strong>${action.action_type}</strong>：
                    <p>${action.content}</p>
                </div>
            `;
        });
        actionsHtml += '</div>';

        modalBody.innerHTML = `
            <h3>事件 #${event.id}: ${event.event_title}</h3>
            <div class="event-details-grid">
                <div><strong>嚴重性:</strong> ${event.severity}</div>
                <div><strong>狀態:</strong> <span id="current-event-status">${event.status}</span></div>
                <div><strong>負責人:</strong> ${event.assigned_to || '未指派'}</div>
                <div><strong>發生時間:</strong> ${new Date(event.event_time).toLocaleString()}</div>
                <div><strong>預計完成日期:</strong> ${event.due_date || '未設定'}</div>
                <div><strong>事件類型:</strong> ${event.event_type || '未設定'}</div>
                <div><strong>影響範圍:</strong> ${event.impact_scope || '未設定'}</div>
                <div class="full-width"><strong>根本原因:</strong> ${event.root_cause || '未設定'}</div>
            </div>
            <hr>
            <h4>更新事件狀態</h4>
            <div class="form-group">
                <label for="update-status">新狀態:</label>
                <select id="update-status">
                    <option value="assigned">已指派 (Assigned)</option>
                    <option value="in_progress">處理中 (In Progress)</option>
                    <option value="closed">已結案 (Closed)</option>
                </select>
                <button id="update-status-btn" class="secondary">更新狀態</button>
            </div>
            <hr>
            ${actionsHtml}
            <hr>
            <h4>新增行動方案</h4>
            <form id="add-action-form" class="form-container">
                <input type="hidden" name="event_id" value="${eventId}">
                <div class="form-group"><label>行動類型:</label><select name="action_type"><option value="comment">一般備註</option><option value="root_cause">根本原因分析</option><option value="correction">矯正措施</option><option value="prevention">預防措施</option></select></div>
                <div class="form-group"><label>內容描述:</label><textarea name="content" rows="4" required></textarea></div>
                <div class="form-group"><label>記錄人:</label><input type="text" name="author" placeholder="您的姓名"></div>
                <button type="submit" class="primary">新增記錄</button>
            </form>
        `;

        // 設置當前狀態為選單的預設值
        document.getElementById('update-status').value = event.status;

        document.getElementById('update-status-btn').addEventListener('click', () => handleUpdateEventStatus(eventId));
        document.getElementById('add-action-form').addEventListener('submit', handleAddAction);
        document.getElementById('event-modal').style.display = 'block';
    } catch (error) {
        console.error('Show Event Details Error:', error);
        alert('載入事件詳情失敗');
    }
}

async function handleUpdateEventStatus(eventId) {
    const newStatus = document.getElementById('update-status').value;
    try {
        const result = await apiFetch(`/api/events/${eventId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        });
        if (result && result.success) {
            alert('事件狀態已更新！');
            // 更新顯示的狀態
            document.getElementById('current-event-status').textContent = newStatus;
            // 重新載入事件列表以反映變更
            loadEvents();
        } else {
            alert(result && result.error ? result.error : '更新狀態失敗');
        }
    } catch (error) {
        console.error('Update Event Status Error:', error);
        alert('更新狀態時發生錯誤。');
    }
}

async function handleAddAction(e) {
    e.preventDefault();
    const formData = new FormData(e.target);
    const eventId = formData.get('event_id');
    const payload = Object.fromEntries(formData.entries());
    const result = await apiFetch(`/api/events/${eventId}/actions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    if (result && result.success) {
        showEventDetails(eventId);
    }
}