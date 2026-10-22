import React, { useState, useEffect } from 'react';
import { TaskOut, ExecutionLogOut, AgentActionLog, DraftRecord } from '../types';
import { getTaskDetail, runTaskCopilot, getDraft, approveDraft } from '../api';
import { PriorityBadge } from './PriorityBadge';
import { X, Send, Bot, CheckCircle, AlertTriangle, Mail } from 'lucide-react';

interface AgentDrawerProps {
  task: TaskOut | null;
  onClose: () => void;
  onTaskUpdated?: () => void;
}

export const AgentDrawer: React.FC<AgentDrawerProps> = ({ task, onClose, onTaskUpdated }) => {
  if (!task) return null;

  const [instruction, setInstruction] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<ExecutionLogOut[]>([]);
  const [recentActions, setRecentActions] = useState<AgentActionLog[]>([]);
  const [finalResponse, setFinalResponse] = useState<string | null>(null);
  const [stagedDraft, setStagedDraft] = useState<DraftRecord | null>(null);
  const [draftApproved, setDraftApproved] = useState(false);

  // Load existing execution logs from database
  useEffect(() => {
    let isMounted = true;
    getTaskDetail(task.id)
      .then((detail) => {
        if (isMounted) {
          setLogs(detail.logs);
        }
      })
      .catch((err) => console.error('Failed to load task logs:', err));

    return () => {
      isMounted = false;
    };
  }, [task.id]);

  const handleRunCopilot = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!instruction.trim() || loading) return;

    setLoading(true);
    setError(null);
    setFinalResponse(null);
    setStagedDraft(null);
    setDraftApproved(false);

    try {
      const result = await runTaskCopilot(task.id, instruction);
      setFinalResponse(result.final_response);
      setRecentActions(result.actions_taken);

      // Check if any tool action created a draft_id
      for (const action of result.actions_taken) {
        if (action.tool_name === 'draft_email_reply') {
          const outputData = action.output?.data as Record<string, unknown> | undefined;
          if (outputData && typeof outputData.draft_id === 'string') {
            const draft = await getDraft(outputData.draft_id).catch(() => null);
            if (draft) {
              setStagedDraft(draft);
            }
          }
        }
      }


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
    if (!stagedDraft) return;
    try {
      await approveDraft(stagedDraft.draft_id);
      setDraftApproved(true);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to approve draft');
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        right: 0,
        bottom: 0,
        width: '560px',
        maxWidth: '90vw',
        backgroundColor: '#ffffff',
        boxShadow: '-4px 0 20px rgba(0,0,0,0.15)',
        zIndex: 1000,
        display: 'flex',
        flexDirection: 'column',
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
          <h2 style={{ margin: 0, fontSize: '18px', fontWeight: '600', color: '#111827' }}>
            Task Co-Pilot
          </h2>
        </div>
        <button
          onClick={onClose}
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

      {/* Task Summary Banner */}
      <div style={{ padding: '16px 20px', borderBottom: '1px solid #f3f4f6', backgroundColor: '#ffffff' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
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
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '20px',
          display: 'flex',
          flexDirection: 'column',
          gap: '16px',
          backgroundColor: '#fafafa',
        }}
      >
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

        {/* Real-time Final Response */}
        {finalResponse && (
          <div
            style={{
              padding: '16px',
              backgroundColor: '#ffffff',
              border: '1px solid #10b981',
              borderRadius: '8px',
              boxShadow: '0 2px 4px rgba(0,0,0,0.05)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px', color: '#059669' }}>
              <CheckCircle size={16} />
              <strong style={{ fontSize: '14px' }}>Co-Pilot Response</strong>
            </div>
            <div style={{ fontSize: '14px', color: '#1f2937', lineHeight: '1.5', whiteSpace: 'pre-wrap' }}>
              {finalResponse}
            </div>
          </div>
        )}

        {/* Staged Draft Review Box (HITL Gate) */}
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

        {/* Real-time Actions Taken */}
        {recentActions.length > 0 && (
          <div>
            <span style={{ fontSize: '12px', fontWeight: '600', color: '#6b7280', textTransform: 'uppercase' }}>
              Actions Executed in this Run:
            </span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '6px' }}>
              {recentActions.map((action, i) => (
                <div
                  key={i}
                  style={{
                    padding: '10px 12px',
                    backgroundColor: '#ffffff',
                    border: '1px solid #e5e7eb',
                    borderRadius: '6px',
                    fontSize: '12px',
                  }}
                >
                  <div style={{ fontWeight: '600', color: '#1f2937', marginBottom: '4px' }}>
                    Tool: <code>{action.tool_name}</code>
                  </div>
                  {action.thought && (
                    <div style={{ color: '#4b5563', marginBottom: '4px' }}>
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

        {/* Existing Historical Execution Logs from SQLite */}
        {logs.length > 0 && (
          <div style={{ marginTop: '12px' }}>
            <span style={{ fontSize: '12px', fontWeight: '600', color: '#6b7280', textTransform: 'uppercase' }}>
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
  );
};
