// --- 全域變數 ---
let baselineChart = null;

// --- 初始化 ---
document.addEventListener('DOMContentLoaded', () => {
    setupRegressionPage();
    loadRegressionBaselines();
});


// --- 共用函式 ---
async function apiFetch(url, options = {}) {
    try {
        const response = await fetch(url, options);
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `伺服器錯誤，狀態碼: ${response.status}` }));
            throw new Error(errorData.error || `HTTP 錯誤!`);
        }
        return response.json();
    } catch (error) {
        console.error('API 請求失敗:', url, error);
        alert(`操作失敗: ${error.message}`);
        return null;
    }
}


// --- 迴歸基線頁面邏輯 ---
function setupRegressionPage() {
    // 綁定所有事件監聽器
    document.getElementById('add-factor-btn')?.addEventListener('click', addFactorInput);
    document.getElementById('regression-baseline-form')?.addEventListener('submit', handleRegressionBaselineSubmit);
    document.getElementById('select-baseline-for-data')?.addEventListener('change', handleBaselineSelectionForData);
    document.getElementById('save-data-btn')?.addEventListener('click', saveDataEntry);
    
    // 預設新增一個因子輸入框
    addFactorInput();
}

function addFactorInput() {
    const container = document.getElementById('rb-factors-container');
    if (!container) return;
    const factorRow = document.createElement('div');
    factorRow.className = 'factor-row form-group'; // 使用 form-group 來對齊
    factorRow.innerHTML = `
        <input type="text" class="factor-name" placeholder="因子名稱 (例如: 工時)" required>
        <input type="number" step="any" class="factor-coeff" placeholder="係數" required>
        <button type="button" onclick="this.parentElement.remove()" class="secondary">移除</button>
    `;
    container.appendChild(factorRow);
}

async function handleRegressionBaselineSubmit(e) {
    e.preventDefault();
    const factors = Array.from(document.querySelectorAll('.factor-row')).map(row => ({
        name: row.querySelector('.factor-name').value,
        coeff: row.querySelector('.factor-coeff').value
    })).filter(f => f.name && f.coeff);

    if (factors.length === 0) {
        alert("請至少新增一個迴歸因子。");
        return;
    }

    const payload = {
        name: document.getElementById('rb-name').value,
        year: document.getElementById('rb-year').value,
        intercept: document.getElementById('rb-intercept').value,
        r2: document.getElementById('rb-r2').value || null,
        notes: "", // 'notes' 欄位目前未使用，設為空字串
        factors: factors
    };

    const result = await apiFetch('/api/regression_baselines', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    if (result && result.success) {
        alert(result.message);
        e.target.reset();
        document.getElementById('rb-factors-container').innerHTML = ''; // 清空因子
        addFactorInput(); // 加回一個空的
        loadRegressionBaselines(); // 重新載入下拉選單
    }
}

async function loadRegressionBaselines() {
    const baselines = await apiFetch('/api/regression_baselines');
    const select = document.getElementById('select-baseline-for-data');
    if (!select) return;

    const currentVal = select.value;
    select.innerHTML = '<option value="">-- 請選擇 --</option>';
    if (baselines) {
        baselines.forEach(b => select.add(new Option(`${b.year} - ${b.name}`, b.id)));
    }
    select.value = currentVal;
}

async function handleBaselineSelectionForData(e) {
    const baselineId = e.target.value;
    const dataEntrySection = document.getElementById('data-entry-section');
    if (!baselineId) {
        dataEntrySection.style.display = 'none';
        return;
    }
    
    const data = await apiFetch(`/api/regression_baselines/${baselineId}`);
    if (!data) return;

    document.getElementById('data-entry-title').textContent = `輸入/檢視 "${data.baseline.name}" 的監控數據`;
    const tableHead = document.getElementById('data-entry-table').querySelector('thead');
    const tableBody = document.getElementById('data-entry-table').querySelector('tbody');
    
    let headerHtml = '<tr><th>月份</th>';
    data.factors.forEach(f => headerHtml += `<th>${f.factor_name} (實際值)</th>`);
    headerHtml += '<th>實際能耗</th><th>基線標準</th><th>差異</th><th>差異 (%)</th></tr>';
    tableHead.innerHTML = headerHtml;

    tableBody.innerHTML = '';
    const formula = { intercept: data.baseline.formula_intercept, factors: data.factors };

    for (let month = 1; month <= 12; month++) {
        const row = tableBody.insertRow();
        row.dataset.month = month;
        
        const monthData = data.monitored_data[month] || {};
        const factorsData = monthData.factors || {};
        const actualConsumption = monthData.actual_consumption ?? ''; // 使用 ?? 確保 null 和 undefined 都變為 ''

        let rowHtml = `<td>${month}月</td>`;
        data.factors.forEach(f => {
            const factorValue = factorsData[f.factor_name] ?? '';
            rowHtml += `<td><input type="number" step="any" class="factor-input" data-factor-name="${f.factor_name}" value="${factorValue}"></td>`;
        });
        rowHtml += `<td><input type="number" step="any" class="actual-consumption-input" value="${actualConsumption}"></td>`;
        
        const { baselineStandard, diff, diffPercent } = calculateRow(formula, factorsData, actualConsumption);
        
        rowHtml += `<td class="baseline-standard">${baselineStandard}</td><td class="diff">${diff}</td><td class="diff-percent ${Math.abs(parseFloat(diffPercent)) > 10 ? 'highlight' : ''}">${diffPercent}</td>`;
        row.innerHTML = rowHtml;
    }
    
    updateDataEntryChart();
    dataEntrySection.style.display = 'block';
}

function calculateRow(formula, factorsData, actualConsumption) {
    let baselineStandard = formula.intercept;
    let allFactorsEntered = true;

    formula.factors.forEach(f => {
        const factorValue = factorsData[f.factor_name];
        if (factorValue === undefined || factorValue === '' || factorValue === null) {
            allFactorsEntered = false;
        } else {
            baselineStandard += parseFloat(factorValue) * f.coefficient;
        }
    });

    if (!allFactorsEntered) return { baselineStandard: '', diff: '', diffPercent: '' };
    if (actualConsumption === '' || actualConsumption === null || actualConsumption === undefined) {
        return { baselineStandard: baselineStandard.toFixed(2), diff: '', diffPercent: '' };
    }
    
    const actual = parseFloat(actualConsumption);
    const diff = baselineStandard - actual;
    const diffPercent = (baselineStandard !== 0) ? (diff / baselineStandard * 100) : 0;

    return {
        baselineStandard: baselineStandard.toFixed(2),
        diff: diff.toFixed(2),
        diffPercent: `${diffPercent.toFixed(1)}%`
    };
}

async function saveDataEntry() {
    const baselineId = document.getElementById('select-baseline-for-data').value;
    if (!baselineId) return;

    const rows = document.getElementById('data-entry-table')?.querySelector('tbody')?.rows;
    if (!rows) return;

    const requests = [];
    for (const row of rows) {
        const month = row.dataset.month;
        const factors = {};
        let hasData = false;
        
        row.querySelectorAll('.factor-input').forEach(input => {
            if (input.value !== '') {
                factors[input.dataset.factorName] = parseFloat(input.value);
                hasData = true;
            }
        });

        const actualInput = row.querySelector('.actual-consumption-input');
        const actualConsumption = actualInput ? actualInput.value : '';
        if (actualConsumption !== '') hasData = true;

        if (hasData) {
            const payload = {
                baseline_id: parseInt(baselineId),
                month: parseInt(month),
                factors: factors,
                actual_consumption: actualConsumption !== '' ? parseFloat(actualConsumption) : null
            };
            requests.push(apiFetch('/api/monitored_data', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            }));
        }
    }
    
    const results = await Promise.all(requests);
    const successCount = results.filter(r => r && r.success).length;

    if (successCount > 0) {
        alert(`成功儲存 ${successCount} 個月份的數據！`);
        // 重新觸發 change 事件來刷新表格和圖表
        document.getElementById('select-baseline-for-data').dispatchEvent(new Event('change'));
    } else {
        alert("沒有可儲存的數據。");
    }
}

function updateDataEntryChart() {
    const tableBody = document.getElementById('data-entry-table')?.querySelector('tbody');
    if (!tableBody) return;

    const reportData = [];
    for (const row of tableBody.rows) {
        reportData.push({
            month: row.cells[0].textContent,
            baseline: row.cells[row.cells.length - 3].textContent !== '' ? parseFloat(row.cells[row.cells.length - 3].textContent) : null,
            actual: row.querySelector('.actual-consumption-input').value !== '' ? parseFloat(row.querySelector('.actual-consumption-input').value) : null,
        });
    }

    const ctx = document.getElementById('baseline-chart')?.getContext('2d');
    if (!ctx) return;
    if (baselineChart) baselineChart.destroy();
    
    baselineChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: reportData.map(d => d.month),
            datasets: [
                {
                    label: '基線標準',
                    data: reportData.map(d => d.baseline),
                    borderColor: 'rgb(255, 99, 132)',
                    backgroundColor: 'rgba(255, 99, 132, 0.5)',
                    borderDash: [5, 5],
                    fill: false,
                },
                {
                    label: '量測數據',
                    data: reportData.map(d => d.actual),
                    borderColor: 'rgb(54, 162, 235)',
                    backgroundColor: 'rgba(54, 162, 235, 0.5)',
                    fill: false,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: { display: true, text: '能源基線管理圖', font: { size: 16 } },
                legend: { position: 'top' }
            },
            scales: {
                y: { beginAtZero: true, title: { display: true, text: '能耗' } }
            }
        }
    });
}