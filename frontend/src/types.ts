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