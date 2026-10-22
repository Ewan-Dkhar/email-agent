import React, { useState, useEffect, useRef } from 'react';
import { TaskOut, ExecutionLogOut, AgentActionLog, DraftRecord } from '../types';
import { getTaskDetail, runTaskCopilot, getDraft, approveDraft } from '../api';
import { PriorityBadge } from './PriorityBadge';
import { X, Send, Bot, CheckCircle, AlertTriangle, Mail, User, RotateCcw } from 'lucide-react';

interface AgentDrawerProps {
  task: TaskOut;
  onClose: () => void;
  onTaskUpdated?: () => void;
}

export interface ConversationTurn {
  instruction: string;
  response: string;
  actions: AgentActionLog[];
  stagedDraft?: DraftRecord | null;
  timestamp: string;
}

interface TaskSessionState {
  turns: ConversationTurn[];
  stagedDraft: DraftRecord | null;
  draftApproved: boolean;
}

const STORAGE_PREFIX = 'email_agent_copilot_session_';

function loadTaskSession(taskId: number): TaskSessionState {
  try {
    const raw = localStorage.getItem(`${STORAGE_PREFIX}${taskId}`);
    if (raw) {
      return JSON.parse(raw);
    }
  } catch (e) {
    console.warn('Failed to load task session:', e);
  }
  return { turns: [], stagedDraft: null, draftApproved: false };
}

function saveTaskSession(taskId: number, state: TaskSessionState) {
  try {
    localStorage.setItem(`${STORAGE_PREFIX}${taskId}`, JSON.stringify(state));
  } catch (e) {
    console.warn('Failed to save task session:', e);
  }
}

export const AgentDrawer: React.FC<AgentDrawerProps> = ({ task, onClose, onTaskUpdated }) => {
  const [instruction, setInstruction] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<ExecutionLogOut[]>([]);

  // Persistent session state for this task
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [stagedDraft, setStagedDraft] = useState<DraftRecord | null>(null);
  const [draftApproved, setDraftApproved] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const drawerRef = useRef<HTMLDivElement>(null);

  const handleClose = () => {
    document.body.style.overflow = 'unset';
    onClose();
  };

  // 1. Lock body scroll while drawer is mounted, reliably restore on unmount
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = 'unset';
    };
  }, []);

  // 2. Close on Escape key press or click/tap outside
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        handleClose();
      }
    };
    const handleClickOutside = (e: MouseEvent) => {
      if (drawerRef.current && !drawerRef.current.contains(e.target as Node)) {
        handleClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [onClose]);

  // 3. Load persistent session state whenever the selected task opens or changes
  useEffect(() => {
    if (task) {
      const saved = loadTaskSession(task.id);
      setTurns(saved.turns);
      setStagedDraft(saved.stagedDraft);
      setDraftApproved(saved.draftApproved);
      setError(null);
      setInstruction('');

      // Also refresh SQLite execution logs from backend
      getTaskDetail(task.id)
        .then((detail) => setLogs(detail.logs))
        .catch((err) => console.error('Failed to load task logs:', err));
    }
  }, [task?.id]);

  // Scroll to bottom on new turns or loading
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [turns, loading, stagedDraft]);

  const handleRunCopilot = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!instruction.trim() || loading || !task) return;

    const currentInstruction = instruction.trim();
    setLoading(true);
    setError(null);

    try {
      const result = await runTaskCopilot(task.id, currentInstruction);

      // Detect if this run produced a staged draft
      let detectedDraft: DraftRecord | null = null;
      for (const action of result.actions_taken) {
        if (action.tool_name === 'draft_email_reply') {
          const outputData = action.output?.data as Record<string, unknown> | undefined;
          if (outputData && typeof outputData.draft_id === 'string') {
            const draft = await getDraft(outputData.draft_id).catch(() => null);
            if (draft) {
              detectedDraft = draft;
            }
          }
        }
      }

      const newTurn: ConversationTurn = {
        instruction: currentInstruction,
        response: result.final_response,
        actions: result.actions_taken,
        stagedDraft: detectedDraft,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };

      const updatedTurns = [...turns, newTurn];
      const nextDraft = detectedDraft || stagedDraft;
      const nextDraftApproved = detectedDraft ? false : draftApproved;

      setTurns(updatedTurns);
      if (detectedDraft) {
        setStagedDraft(detectedDraft);
        setDraftApproved(false);
      }

      // Persist to local storage
      saveTaskSession(task.id, {
        turns: updatedTurns,
        stagedDraft: nextDraft,
        draftApproved: nextDraftApproved,
      });

      // Refresh DB logs
      const detail = await getTaskDetail(task.id);
      setLogs(detail.logs);
      setInstruction('');
      if (onTaskUpdated) onTaskUpdated();
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : 'Co-pilot execution failed';
      setError(errMsg);
    } finally {
      setLoading(false);
    }
  };

  const handleApproveDraft = async () => {
    if (!stagedDraft || !task) return;
    try {
      await approveDraft(stagedDraft.draft_id);
      setDraftApproved(true);
      saveTaskSession(task.id, {
        turns,
        stagedDraft,
        draftApproved: true,
      });
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to approve draft');
    }
  };

  const handleClearChat = () => {
    if (!task) return;
    if (confirm('Clear the conversation history for this task?')) {
      localStorage.removeItem(`${STORAGE_PREFIX}${task.id}`);
      setTurns([]);
      setStagedDraft(null);
      setDraftApproved(false);
      setError(null);
    }
  };

  return (
    <>
      {/* Backdrop Overlay - Tap outside to close */}
      <div
        onClick={handleClose}
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.45)',
          zIndex: 999,
          backdropFilter: 'blur(1.5px)',
          transition: 'all 0.2s ease',
        }}
        aria-hidden="true"
      />

      {/* Sidebar Container */}
      <div
        ref={drawerRef}
        style={{
          position: 'fixed',
          top: 0,
          right: 0,
          bottom: 0,
          width: '560px',
          maxWidth: '92vw',
          backgroundColor: '#ffffff',
          boxShadow: '-4px 0 24px rgba(0,0,0,0.18)',
          zIndex: 1000,
          display: 'flex',
          flexDirection: 'column',
          overscrollBehavior: 'contain',
        }}
      >
        {/* Drawer Header */}
        <div
          style={{
            padding: '16px 20px',
            borderBottom: '1px solid #e5e7eb',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            backgroundColor: '#f9fafb',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Bot size={20} color="#1f2937" />
            <h2 style={{ margin: 0, fontSize: '17px', fontWeight: '600', color: '#111827' }}>
              Task Co-Pilot
            </h2>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {turns.length > 0 && (
              <button
                onClick={handleClearChat}
                title="Clear conversation for this task"
                style={{
                  background: 'none',
                  border: '1px solid #e5e7eb',
                  borderRadius: '6px',
                  padding: '4px 8px',
                  fontSize: '12px',
                  color: '#6b7280',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                }}
              >
                <RotateCcw size={12} />
                Clear
              </button>
            )}

            <button
              onClick={handleClose}
              title="Close (Esc)"
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                padding: '4px',
                borderRadius: '4px',
                color: '#6b7280',
              }}
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Task Summary Banner */}
        <div style={{ padding: '14px 20px', borderBottom: '1px solid #f3f4f6', backgroundColor: '#ffffff' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
            <PriorityBadge priority={task.priority_tier} />
            <span style={{ fontSize: '14px', fontWeight: '600', color: '#111827' }}>
              {task.title}
            </span>
          </div>
          <p style={{ margin: 0, fontSize: '13px', color: '#4b5563', lineHeight: '1.4' }}>
            {task.summary}
          </p>
        </div>

        {/* Conversation & Execution Log Area */}
        <div
          ref={scrollRef}
          style={{
            flex: 1,
            overflowY: 'auto',
            overscrollBehavior: 'contain',
            padding: '20px',
            display: 'flex',
            flexDirection: 'column',
            gap: '16px',
            backgroundColor: '#fafafa',
          }}
        >
          {/* Welcome Prompt if no conversation turns yet */}
          {turns.length === 0 && (
            <div
              style={{
                padding: '16px',
                backgroundColor: '#ffffff',
                border: '1px dashed #d1d5db',
                borderRadius: '8px',
                textAlign: 'center',
                color: '#6b7280',
                fontSize: '13px',
              }}
            >
              <Bot size={28} style={{ margin: '0 auto 8px auto', color: '#9ca3af' }} />
              <p style={{ margin: '0 0 6px 0', fontWeight: '600', color: '#374151' }}>
                How can I assist you with this task?
              </p>
              <p style={{ margin: 0, fontSize: '12px' }}>
                Ask me to draft an email reply, inspect local reference files in your workspace, or suggest action steps.
              </p>
            </div>
          )}

          {/* Conversation History Turns */}
          {turns.map((turn, index) => (
            <div key={index} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {/* User Prompt Bubble */}
              <div
                style={{
                  alignSelf: 'flex-end',
                  maxWidth: '85%',
                  backgroundColor: '#1f2937',
                  color: '#ffffff',
                  padding: '10px 14px',
                  borderRadius: '12px 12px 2px 12px',
                  fontSize: '13px',
                  lineHeight: '1.4',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '2px', opacity: 0.75, fontSize: '11px' }}>
                  <User size={12} />
                  <span>You • {turn.timestamp}</span>
                </div>
                <div>{turn.instruction}</div>
              </div>

              {/* Actions Executed during this turn */}
              {turn.actions.length > 0 && (
                <div style={{ padding: '0 4px' }}>
                  <span style={{ fontSize: '11px', fontWeight: '600', color: '#6b7280', textTransform: 'uppercase' }}>
                    Actions taken by Agent:
                  </span>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '4px' }}>
                    {turn.actions.map((action, i) => (
                      <div
                        key={i}
                        style={{
                          padding: '8px 10px',
                          backgroundColor: '#ffffff',
                          border: '1px solid #e5e7eb',
                          borderRadius: '6px',
                          fontSize: '12px',
                        }}
                      >
                        <div style={{ fontWeight: '600', color: '#1f2937', marginBottom: '2px' }}>
                          Tool: <code>{action.tool_name}</code>
                        </div>
                        {action.thought && (
                          <div style={{ color: '#4b5563', marginBottom: '2px' }}>
                            <em>Thought:</em> {action.thought}
                          </div>
                        )}
                        <div style={{ color: '#6b7280', fontFamily: 'monospace', fontSize: '11px' }}>
                          Result: {JSON.stringify(action.output)}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Agent Response Card */}
              <div
                style={{
                  alignSelf: 'flex-start',
                  width: '100%',
                  padding: '14px',
                  backgroundColor: '#ffffff',
                  border: '1px solid #10b981',
                  borderRadius: '8px',
                  boxShadow: '0 2px 4px rgba(0,0,0,0.04)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px', color: '#059669' }}>
                  <CheckCircle size={15} />
                  <strong style={{ fontSize: '13px' }}>Co-Pilot Response</strong>
                </div>
                <div style={{ fontSize: '13px', color: '#1f2937', lineHeight: '1.5', whiteSpace: 'pre-wrap' }}>
                  {turn.response}
                </div>
              </div>
            </div>
          ))}

          {/* Staged Draft Review Box (Human-in-the-Loop Approval Gate) */}
          {stagedDraft && (
            <div
              style={{
                padding: '16px',
                backgroundColor: '#ffffff',
                border: '1px solid #3b82f6',
                borderRadius: '8px',
                boxShadow: '0 2px 6px rgba(59,130,246,0.1)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '10px', color: '#2563eb' }}>
                <Mail size={16} />
                <strong style={{ fontSize: '14px' }}>Staged Email Draft (Pending Approval)</strong>
              </div>
              <div style={{ fontSize: '13px', color: '#374151', marginBottom: '8px' }}>
                <div><strong>To:</strong> {stagedDraft.recipient}</div>
                <div><strong>Subject:</strong> {stagedDraft.subject}</div>
              </div>
              <div
                style={{
                  backgroundColor: '#f9fafb',
                  padding: '12px',
                  borderRadius: '6px',
                  fontSize: '13px',
                  whiteSpace: 'pre-wrap',
                  fontFamily: 'monospace',
                  border: '1px solid #e5e7eb',
                  marginBottom: '12px',
                }}
              >
                {stagedDraft.body_markdown}
              </div>
              <button
                onClick={handleApproveDraft}
                disabled={draftApproved}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '8px 16px',
                  fontSize: '13px',
                  fontWeight: '600',
                  borderRadius: '6px',
                  border: 'none',
                  backgroundColor: draftApproved ? '#10b981' : '#2563eb',
                  color: '#ffffff',
                  cursor: draftApproved ? 'default' : 'pointer',
                }}
              >
                <CheckCircle size={15} />
                {draftApproved ? 'Draft Approved!' : 'Approve & Stage for Sending'}
              </button>
            </div>
          )}

          {/* Thinking / Running Indicator */}
          {loading && (
            <div
              style={{
                padding: '12px 16px',
                backgroundColor: '#ffffff',
                border: '1px solid #e5e7eb',
                borderRadius: '8px',
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                color: '#4b5563',
                fontSize: '13px',
              }}
            >
              <Bot size={18} style={{ animation: 'spin 1.5s linear infinite' }} />
              <span>Co-pilot is reasoning and executing skills...</span>
            </div>
          )}

          {/* Error Alert */}
          {error && (
            <div
              style={{
                padding: '12px 14px',
                backgroundColor: '#fee2e2',
                border: '1px solid #f87171',
                borderRadius: '6px',
                color: '#991b1b',
                fontSize: '13px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}
            >
              <AlertTriangle size={18} />
              <span>{error}</span>
            </div>
          )}

          {/* Historical Database Execution Logs */}
          {logs.length > 0 && (
            <div style={{ marginTop: '14px' }}>
              <span style={{ fontSize: '11px', fontWeight: '600', color: '#6b7280', textTransform: 'uppercase' }}>
                Historical Audit Log ({logs.length} entries):
              </span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '6px' }}>
                {logs.map((log) => (
                  <div
                    key={log.id}
                    style={{
                      padding: '10px 12px',
                      backgroundColor: '#ffffff',
                      border: '1px solid #e5e7eb',
                      borderRadius: '6px',
                      fontSize: '12px',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                      <span style={{ fontWeight: '600', color: '#111827' }}>
                        {log.tool_name}
                      </span>
                      <span style={{ color: '#9ca3af', fontSize: '11px' }}>
                        {log.created_at}
                      </span>
                    </div>
                    {log.thought && (
                      <p style={{ margin: '0 0 4px 0', color: '#4b5563' }}>
                        {log.thought}
                      </p>
                    )}
                    <pre
                      style={{
                        margin: 0,
                        backgroundColor: '#f3f4f6',
                        padding: '6px 8px',
                        borderRadius: '4px',
                        overflowX: 'auto',
                        fontSize: '11px',
                      }}
                    >
                      {log.tool_output}
                    </pre>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Drawer Input Footer */}
        <form
          onSubmit={handleRunCopilot}
          style={{
            padding: '16px 20px',
            borderTop: '1px solid #e5e7eb',
            backgroundColor: '#ffffff',
            display: 'flex',
            gap: '8px',
          }}
        >
          <input
            type="text"
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder="e.g. 'Draft an email reply saying I will attend' or 'Check notes.txt'..."
            disabled={loading}
            style={{
              flex: 1,
              padding: '10px 14px',
              fontSize: '14px',
              border: '1px solid #d1d5db',
              borderRadius: '6px',
              outline: 'none',
            }}
          />
          <button
            type="submit"
            disabled={loading || !instruction.trim()}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '10px 18px',
              fontSize: '14px',
              fontWeight: '600',
              backgroundColor: loading || !instruction.trim() ? '#9ca3af' : '#1f2937',
              color: '#ffffff',
              border: 'none',
              borderRadius: '6px',
              cursor: loading || !instruction.trim() ? 'not-allowed' : 'pointer',
            }}
          >
            {loading ? 'Thinking...' : 'Run'}
            {!loading && <Send size={15} />}
          </button>
        </form>
      </div>
    </>
  );
};
