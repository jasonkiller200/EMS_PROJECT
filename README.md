# 能源管理系統 (EMS) 專案

## 專案簡介

這是一個基於 Flask 框架開發的能源管理系統 (Energy Management System, EMS) 專案。它旨在幫助用戶監控能源消耗、管理迴歸基準線、追蹤能源績效指標 (EnPI) 以及處理異常事件。本系統採用 SQLite 作為輕量級資料庫，並利用 Pandas 進行數據處理和分析，提供直觀的網頁介面。

## 主要功能

*   **即時儀表板 (Real-time Dashboard)**：
    *   提供多個可自定義的圖表，展示關鍵能源數據的即時趨勢。
    *   支援小時、日、月等多種時間粒度的數據聚合。
    *   可配置數據來源表、時間欄位、數值欄位、聚合方法（總和/平均）和圖表類型。

*   **迴歸基準線管理 (Regression Baseline Management)**：
    *   建立和管理能源消耗的迴歸基準線模型。
    *   記錄基準線的名稱、年份、截距和 R² 值。
    *   定義影響能源消耗的因子及其係數。
    *   追蹤實際監測數據與基準線的偏差。

*   **能源績效指標 (EnPI) 追蹤**：
    *   定義和管理各種 EnPI，例如單位產量能耗、單位面積能耗等。
    *   支援手動輸入數據或從資料庫自動提取數據來計算 EnPI。
    *   可設定 EnPI 目標值，並與實際值進行比較。
    *   提供按月度的 EnPI 報告。

*   **異常事件與行動方案管理 (Alarm Event & Action Plan Management)**：
    *   手動建立異常事件，記錄事件標題、嚴重性、負責人、預計完成日期、事件類型、影響範圍和根本原因。
    *   追蹤事件的狀態（例如：已指派、處理中、已結案）。
    *   為每個事件新增行動方案，記錄處理歷程、行動類型（備註、根本原因分析、矯正措施、預防措施）和內容。
    *   提供事件列表篩選功能。

## 技術棧

*   **後端**：Python 3.x, Flask, SQLite3, Pandas
*   **前端**：HTML5, CSS3, JavaScript, Chart.js (用於圖表)
*   **資料庫**：SQLite (`url_manager.db`)

## 安裝與運行

1.  **克隆專案 (Clone the repository)**：
    ```bash
    git clone https://github.com/jasonkiller200/EMS_PROJECT.git
    cd EMS_PROJECT
    ```

2.  **建立並激活虛擬環境 (Create and activate virtual environment)**：
    ```bash
    python -m venv .venv
    # Windows
    .venv\Scripts\activate
    # macOS/Linux
    source .venv/bin/activate
    ```

3.  **安裝依賴 (Install dependencies)**：
    ```bash
    pip install Flask pandas openpyxl tkcalendar
    # 如果您有 requirements.txt 檔案，可以使用：
    # pip install -r requirements.txt
    ```

4.  **初始化資料庫 (Initialize Database)**：
    專案啟動時會自動檢查並初始化 `url_manager.db`。如果資料庫不存在，`data_collector.py` 中的 `init_db()` 函數會創建必要的表格。您也可以手動運行 `data_collector.py` 來初始化。
    ```bash
    python data_collector.py
    ```

5.  **運行 Flask 應用程式 (Run Flask Application)**：
    ```bash
    python app.py
    ```
    應用程式將在 `http://127.0.0.1:5001` 運行。

## 資料庫說明

本專案使用 `url_manager.db` 作為 SQLite 資料庫檔案。主要表格包括：

*   `DashboardCharts`：儲存儀表板圖表的配置。
*   `DashboardSeries`：儲存每個圖表中的數據系列配置。
*   `RegressionBaselines`：儲存迴歸基準線模型的基本資訊。
*   `RegressionFactors`：儲存迴歸基準線模型的因子及其係數。
*   `MonitoredData`：儲存與迴歸基準線相關的實際監測數據。
*   `EnPI_Definitions`：儲存能源績效指標的定義。
*   `EnPI_Manual_Data`：儲存手動輸入的 EnPI 相關數據。
*   `EnPI_Targets`：儲存 EnPI 的目標值。
*   `Alarm_Events`：儲存異常事件的詳細資訊，包括事件標題、嚴重性、狀態、負責人、事件類型、影響範圍和根本原因等。
*   `Action_Plans`：儲存針對異常事件採取的行動方案和處理歷程。

## 最近更新

*   **增強事件管理功能**：
    *   在異常事件中新增了「事件類型」、「影響範圍」和「根本原因」等屬性，提供更全面的事件描述。
    *   前端介面已更新，支援這些新屬性的輸入和顯示。
    *   事件狀態的預設值和可選狀態已從「開啟中」調整為「已指派」，並在前端和後端同步更新。
*   **修復儀表板數據加載問題**：
    *   解決了在數據為空或數據類型不匹配時，儀表板加載可能導致的伺服器內部錯誤。
    *   優化了 Pandas 數據處理邏輯，確保數據轉換的穩定性。

## 貢獻

歡迎對本專案提出建議或貢獻。如果您發現任何問題或有改進意見，請隨時提交 Issue 或 Pull Request。

## 許可證

本專案採用 MIT 許可證。詳情請參閱 `LICENSE` 檔案 (如果存在)。