import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, Route, Routes } from 'react-router-dom';
import {
  ArrowRight,
  ChevronRight,
  CircleHelp,
  FolderOpen,
  Network,
  ShieldCheck,
} from 'lucide-react';
import { api } from './api';
import { Modal } from './components/Modal';
import { Dashboard } from './features/cases/Dashboard';
import { CreateCase } from './features/cases/CreateCase';
import { CaseWorkspace } from './features/cases/CaseWorkspace';

export function App() {
  const [creating, setCreating] = useState(false);
  const [help, setHelp] = useState(false);
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 30_000 });
  return (
    <div className="app-shell modern-shell">
      <aside className="sidebar">
        <Link className="brand" to="/" aria-label="TraceGraph · список кейсов">
          <span>
            <Network size={24} />
          </span>
          <div>
            TraceGraph<small>FINANCIAL INTELLIGENCE</small>
          </div>
        </Link>
        <div className="sidebar-section">РАБОЧЕЕ МЕСТО</div>
        <Link to="/" className="nav-link" aria-label="Кейсы" title="Кейсы">
          <FolderOpen size={19} /> Кейсы <ChevronRight size={16} />
        </Link>
        <button
          className="nav-link help-link"
          aria-label="Как это работает"
          title="Как это работает"
          onClick={() => setHelp(true)}
        >
          <CircleHelp size={19} /> Как это работает
        </button>
        <div className="sidebar-bottom">
          <div className="local-symbol">
            <ShieldCheck size={20} />
          </div>
          <strong>Локальное пространство</strong>
          <p>
            История и файлы доступны
            <br />
            на этом компьютере.
          </p>
          <span className="version">HACKALEM AI · v0.1</span>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div>
            <span>Рабочее пространство</span>
            <ChevronRight size={14} />
            <strong>Аналитика сети</strong>
          </div>
          <span className={`connection ${health.isSuccess ? 'online' : ''}`}>
            <i />
            {health.isSuccess
              ? 'Система подключена'
              : health.isError
                ? 'Нет соединения'
                : 'Подключение'}
          </span>
        </header>
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard onCreate={() => setCreating(true)} />} />
            <Route path="/cases/:caseId" element={<CaseWorkspace />} />
            <Route
              path="*"
              element={
                <div className="empty-state">
                  <h1>Страница не найдена</h1>
                  <Link to="/" className="button primary">
                    К списку кейсов <ArrowRight size={16} />
                  </Link>
                </div>
              }
            />
          </Routes>
        </main>
      </div>
      {creating && <CreateCase onClose={() => setCreating(false)} />}
      {help && (
        <Modal title="От файлов к исследованию сети" onClose={() => setHelp(false)}>
          <div className="help-content">
            <p>1. Создайте кейс с понятным названием.</p>
            <p>
              2. Загрузите nodes.parquet, edges.parquet и transactions.parquet из одной выгрузки.
            </p>
            <p>
              3. Изучите результат проверки и ограничения данных. Набор и кейс сохраняются после
              перезапуска приложения.
            </p>
            <p>
              4. Запустите анализ сети: изучите рейтинг клиентов и скачайте CSV и JSON. Каждый
              запуск сохраняется в истории выбранного набора. Нажмите на роль или интервал
              приоритета, чтобы отобрать участников. Откройте GID для объяснений и перехода к графу
              соседних переводов. AI-расследования будут подключены следующим этапом.
            </p>
          </div>
          <button className="button primary" onClick={() => setHelp(false)}>
            Понятно
          </button>
        </Modal>
      )}
    </div>
  );
}
