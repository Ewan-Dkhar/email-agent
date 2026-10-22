import React, { useState, useEffect, useCallback } from 'react';
import { TaskOut, TaskStatus, PriorityTier, HealthResponse } from './types';
import { getTasks, updateTaskStatus, syncEmails, getHealth } from './api';
import { TaskCard } from './components/TaskCard';
import { AgentDrawer } from './components/AgentDrawer';
import { Mail, RefreshCw, Activity, Filter, CheckCircle, AlertCircle } from 'lucide-react';

export const App: React.FC = () => {
  const [tasks, setTasks] = useState<TaskOut[]>([]);
  const [selectedTask, setSelectedTask] = useState<TaskOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [statusFilter, setStatusFilter] = useState<TaskStatus | 'ALL'>('ALL');
  const [priorityFilter, setPriorityFilter] = useState<PriorityTier | 'ALL'>('ALL');
  const [notification, setNotification] = useState<string | null>(null);

  const showNotification = (msg: string) => {
    setNotification(msg);
    setTimeout(() => setNotification(null), 4000);
  };

  const loadHealth = useCallback(async () => {
    try {
      const h = await getHealth();
      setHealth(h);
    } catch (e) {
      console.warn('Health check failed:', e);
    }
  }, []);

  const loadTasks = useCallback(async () => {
    setLoading(true);
    try {
      const s = statusFilter === 'ALL' ? undefined : statusFilter;
      const p = priorityFilter === 'ALL' ? undefined : priorityFilter;
      const data = await getTasks(s, p);
      setTasks(data);
    } catch (err: unknown) {
      console.error('Failed to load tasks:', err);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, priorityFilter]);

  useEffect(() => {
    loadHealth();
    loadTasks();
  }, [loadHealth, loadTasks]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      const res = await syncEmails();
      showNotification(`Sync Complete: Ingested ${res.new_emails} emails, created ${res.tasks_created} tasks!`);
      await loadTasks();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Sync failed');
    } finally {
      setSyncing(false);
    }
  };

  const handleStatusChange = async (taskId: number, newStatus: TaskStatus) => {
    try {
      await updateTaskStatus(taskId, newStatus);
      await loadTasks();
      if (selectedTask?.id === taskId) {
        setSelectedTask((prev) => (prev ? { ...prev, status: newStatus } : null));
      }
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Status update failed');
    }
  };

  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#f3f4f6', fontFamily: 'system-ui, -apple-system, sans-serif' }}>
      {/* Top Navbar */}
      <header
        style={{
          backgroundColor: '#ffffff',
          borderBottom: '1px solid #e5e7eb',
          padding: '14px 28px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          boxShadow: '0 1px 2px rgba(0,0,0,0.03)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div
            style={{
              width: '36px',
              height: '36px',
              borderRadius: '8px',
              backgroundColor: '#1f2937',
              color: '#ffffff',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Mail size={20} />
          </div>
          <div>
            <h1 style={{ margin: 0, fontSize: '18px', fontWeight: '700', color: '#111827' }}>
              Autonomous Email Agent
            </h1>
            <span style={{ fontSize: '12px', color: '#6b7280' }}>
              Privacy-Preserving Local Triage & Co-Pilot
            </span>
          </div>
        </div>

        {/* Right side controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          {/* Health indicator */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '12px',
              color: health?.ollama.online ? '#15803d' : '#b45309',
              backgroundColor: health?.ollama.online ? '#f0fdf4' : '#fffbeb',
              padding: '6px 12px',
              borderRadius: '20px',
              border: `1px solid ${health?.ollama.online ? '#bbf7d0' : '#fde68a'}`,
            }}
          >
            <Activity size={14} />
            <span>
              {health?.ollama.online
                ? `Ollama: ${health.ollama.configured_model} (Online)`
                : 'Ollama: Offline'}
            </span>
          </div>

          {/* Sync Button */}
          <button
            onClick={handleSync}
            disabled={syncing}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
              padding: '8px 16px',
              fontSize: '13px',
              fontWeight: '600',
              backgroundColor: syncing ? '#9ca3af' : '#2563eb',
              color: '#ffffff',
              border: 'none',
              borderRadius: '6px',
              cursor: syncing ? 'not-allowed' : 'pointer',
              transition: 'background-color 0.15s ease',
            }}
          >
            <RefreshCw size={15} style={{ animation: syncing ? 'spin 1s linear infinite' : 'none' }} />
            {syncing ? 'Syncing...' : 'Sync Mailbox Now'}
          </button>
        </div>
      </header>

      {/* Notification Toast */}
      {notification && (
        <div
          style={{
            maxWidth: '600px',
            margin: '16px auto -8px auto',
            padding: '12px 18px',
            backgroundColor: '#dcfce7',
            border: '1px solid #86efac',
            borderRadius: '8px',
            color: '#166534',
            fontSize: '14px',
            fontWeight: '500',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            boxShadow: '0 2px 5px rgba(0,0,0,0.05)',
          }}
        >
          <CheckCircle size={18} />
          <span>{notification}</span>
        </div>
      )}

      {/* Main Container */}
      <main style={{ maxWidth: '1100px', margin: '0 auto', padding: '24px 20px' }}>
        {/* Filter Controls Bar */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '20px',
            flexWrap: 'wrap',
            gap: '12px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Filter size={16} color="#6b7280" />
            <span style={{ fontSize: '13px', fontWeight: '600', color: '#4b5563' }}>Filter:</span>

            {/* Status Pills */}
            {(['ALL', 'PENDING', 'COMPLETED', 'DISMISSED'] as const).map((s) => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                style={{
                  padding: '4px 10px',
                  fontSize: '12px',
                  fontWeight: '500',
                  borderRadius: '16px',
                  border: '1px solid',
                  borderColor: statusFilter === s ? '#1f2937' : '#d1d5db',
                  backgroundColor: statusFilter === s ? '#1f2937' : '#ffffff',
                  color: statusFilter === s ? '#ffffff' : '#374151',
                  cursor: 'pointer',
                }}
              >
                {s}
              </button>
            ))}
          </div>

          {/* Priority Filter */}
          <div style={{ display: 'flex', gap: '6px' }}>
            {(['ALL', 'P1_CRITICAL', 'P2_ACTIONABLE', 'P3_INFORMATIONAL'] as const).map((p) => (
              <button
                key={p}
                onClick={() => setPriorityFilter(p)}
                style={{
                  padding: '4px 10px',
                  fontSize: '12px',
                  fontWeight: '500',
                  borderRadius: '16px',
                  border: '1px solid',
                  borderColor: priorityFilter === p ? '#2563eb' : '#d1d5db',
                  backgroundColor: priorityFilter === p ? '#eff6ff' : '#ffffff',
                  color: priorityFilter === p ? '#1d4ed8' : '#374151',
                  cursor: 'pointer',
                }}
              >
                {p === 'ALL' ? 'All Priorities' : p.replace('_', ' ')}
              </button>
            ))}
          </div>
        </div>

        {/* Task Queue List */}
        {loading ? (
          <div style={{ textAlign: 'center', padding: '60px 0', color: '#6b7280', fontSize: '15px' }}>
            Loading tasks...
          </div>
        ) : tasks.length === 0 ? (
          <div
            style={{
              textAlign: 'center',
              padding: '60px 20px',
              backgroundColor: '#ffffff',
              borderRadius: '8px',
              border: '1px dashed #d1d5db',
              color: '#6b7280',
            }}
          >
            <AlertCircle size={32} style={{ margin: '0 auto 12px auto', color: '#9ca3af' }} />
            <h3 style={{ margin: '0 0 6px 0', fontSize: '16px', color: '#111827' }}>No tasks found</h3>
            <p style={{ margin: 0, fontSize: '14px' }}>
              No tasks match your current filter, or your mailbox has not been synced yet.
            </p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            {tasks.map((task) => (
              <TaskCard
                key={task.id}
                task={task}
                onSelectTask={setSelectedTask}
                onStatusChange={handleStatusChange}
              />
            ))}
          </div>
        )}
      </main>

      {/* Interactive ReAct Agent Drawer */}
      <AgentDrawer
        task={selectedTask}
        onClose={() => setSelectedTask(null)}
        onTaskUpdated={loadTasks}
      />
    </div>
  );
};
