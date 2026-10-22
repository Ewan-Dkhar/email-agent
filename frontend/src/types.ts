/**
 * Shared Domain Types and Contracts.
 * Mirrored 1:1 with backend/app/schemas.py to guarantee type safety and zero runtime interface drift.
 */

export type PriorityTier = 'P1_CRITICAL' | 'P2_ACTIONABLE' | 'P3_INFORMATIONAL';

export type TaskStatus = 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'DISMISSED';

export interface ExtractedTask {
  title: string;
  priority: PriorityTier;
  deadline?: string | null;
  summary: string;
  action_url?: string | null;
}

export interface TaskOut {
  id: number;
  email_uid: string;
  title: string;
  deadline?: string | null;
  priority_tier: PriorityTier;
  summary: string;
  action_url?: string | null;
  status: TaskStatus;
  sender: string;
  subject: string;
  created_at: string;
}

export interface ExecutionLogOut {
  id: number;
  task_id: number;
  thought?: string | null;
  tool_name: string;
  tool_input: string; // JSON string
  tool_output: string; // JSON string
  created_at: string;
}

export interface TaskDetailOut {
  task: TaskOut;
  logs: ExecutionLogOut[];
}

export interface AgentActionLog {
  iteration: number;
  thought: string;
  tool_name: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
}

export interface AgentLoopResult {
  task_id: number;
  completed: boolean;
  final_response: string;
  iterations: number;
  actions_taken: AgentActionLog[];
}

export interface SyncResult {
  new_emails: number;
  tasks_created: number;
}

export interface HealthResponse {
  status: string;
  database: string;
  ollama: {
    online: boolean;
    available_models?: string[];
    configured_model?: string;
    model_installed?: boolean;
    error?: string;
  };
}

export interface DraftRecord {
  draft_id: string;
  recipient: string;
  subject: string;
  body_markdown: string;
  status: 'PENDING_APPROVAL' | 'APPROVED';
}
