export type ChatAction = {
  kind: string;
  [key: string]: unknown;
};

export type ButtonAction = {
  label: string;
  style?: 'primary' | 'secondary';
  ui_effect?: 'remove_block' | 'remove_item';
  action: ChatAction;
};

export type ButtonGroupBlock = {
  type: 'button_group';
  title?: string;
  buttons: ButtonAction[];
};

export type ProposalReviewItem = {
  id: string;
  label: string;
  detail?: string;
  buttons: ButtonAction[];
};

export type ProposalReviewBlock = {
  type: 'proposal_review';
  title: string;
  description?: string;
  items: ProposalReviewItem[];
  bulk_buttons?: ButtonAction[];
};

export type MultipleChoiceBlock = {
  type: 'multiple_choice';
  title?: string;
  choices: ButtonAction[];
};

export type ActionBlock = ButtonGroupBlock | ProposalReviewBlock | MultipleChoiceBlock;

export type ChatEnvelope = {
  type: string;
  message: string;
  pending_action?: Record<string, unknown> | null;
  actions?: ActionBlock[];
  clear_history?: boolean;
};

export type ChatEntry = {
  role: string;
  content: string;
  timestamp?: string;
};

export type ChatBootstrap = {
  history: ChatEntry[];
  commands: Array<{ label: string; command: string }>;
};

export type ReviewStats = {
  total_concepts: number;
  total_reviews: number;
  due_now: number;
  avg_mastery: number;
  reviews_last_7d: number;
};

export type DueConcept = {
  id: number;
  title: string;
  mastery_level: number;
  next_review_at?: string | null;
  latest_remark?: string | null;
  topic_ids?: number[];
};

export type ActionSummary = {
  days: number;
  total: number;
  today_total: number;
  by_action: Record<string, number>;
  today_by_action: Record<string, number>;
};

export type ReviewLogEntry = {
  id: number;
  concept_id: number;
  concept_title: string;
  question_asked?: string | null;
  user_response?: string | null;
  quality?: number | null;
  llm_assessment?: string | null;
  reviewed_at?: string | null;
};

export type TopicMapNode = {
  id: number;
  title: string;
  description?: string | null;
  concept_count: number;
  avg_mastery: number;
  due_count: number;
  parent_ids: number[];
  child_ids: number[];
};