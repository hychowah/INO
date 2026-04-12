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

export type TopicSummary = {
  id: number;
  title: string;
  description?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type TopicConcept = {
  id: number;
  title: string;
  description?: string | null;
  mastery_level: number;
  review_count: number;
  interval_days?: number | null;
  next_review_at?: string | null;
  latest_remark?: string | null;
};

export type TopicDetail = TopicSummary & {
  concepts: TopicConcept[];
  children: TopicSummary[];
  parents: TopicSummary[];
};

export type ConceptTopic = {
  id: number;
  title: string;
};

export type ConceptListStatus = 'all' | 'due' | 'upcoming' | 'never';

export type ConceptListSortField =
  | 'id'
  | 'title'
  | 'mastery_level'
  | 'interval_days'
  | 'review_count'
  | 'next_review_at'
  | 'last_reviewed_at';

export type ConceptListItem = {
  id: number;
  title: string;
  mastery_level: number;
  interval_days?: number | null;
  review_count: number;
  next_review_at?: string | null;
  last_reviewed_at?: string | null;
  latest_remark?: string | null;
  topic_ids?: number[];
  topics: ConceptTopic[];
};

export type ConceptListResponse = {
  items: ConceptListItem[];
  total: number;
  page: number;
  per_page: number;
};

export type ConceptRemark = {
  id: number;
  content: string;
  created_at?: string | null;
};

export type ConceptReview = {
  id: number;
  question_asked?: string | null;
  user_response?: string | null;
  quality?: number | null;
  llm_assessment?: string | null;
  reviewed_at?: string | null;
};

export type ConceptRelation = {
  id: number;
  other_concept_id: number;
  other_title: string;
  other_mastery: number;
  relation_type: string;
  note?: string | null;
};

export type ConceptDetail = {
  id: number;
  title: string;
  description?: string | null;
  mastery_level: number;
  interval_days?: number | null;
  next_review_at?: string | null;
  last_reviewed_at?: string | null;
  review_count: number;
  created_at?: string | null;
  remark_summary?: string | null;
  remark_updated_at?: string | null;
  last_quiz_generator_output?: string | null;
  topics: ConceptTopic[];
  remarks: ConceptRemark[];
  recent_reviews: ConceptReview[];
};

export type ActionLogEntry = {
  id: number;
  action: string;
  params?: string | null;
  result_type?: string | null;
  result?: string | null;
  source?: string | null;
  created_at?: string | null;
};

export type ActionLogResponse = {
  items: ActionLogEntry[];
  total: number;
  page: number;
  per_page: number;
};

export type ActionFilterOptions = {
  actions: string[];
  sources: string[];
};

export type ForecastBucket = {
  label: string;
  bucket_key: string;
  count: number;
  avg_mastery: number;
};

export type ForecastSummary = {
  range_type: 'days' | 'weeks' | 'months';
  overdue_count: number;
  buckets: ForecastBucket[];
};

export type ForecastConcept = {
  id: number;
  title: string;
  mastery_level: number;
  next_review_at?: string | null;
  interval_days?: number | null;
  review_count: number;
};

export type GraphConceptNode = {
  id: number;
  title: string;
  description?: string | null;
  review_count: number;
  mastery_level: number;
  next_review_at?: string | null;
  interval_days?: number | null;
  topic_names?: string | null;
  topic_ids: number[];
};

export type GraphTopicNode = {
  id: number;
  title: string;
  description?: string | null;
};

export type GraphConceptEdge = {
  concept_id_low: number;
  concept_id_high: number;
  relation_type: string;
  note?: string | null;
};

export type GraphTopicEdge = {
  parent_id: number;
  child_id: number;
};

export type GraphConceptTopicEdge = {
  concept_id: number;
  topic_id: number;
};

export type GraphResponse = {
  concept_nodes: GraphConceptNode[];
  topic_nodes: GraphTopicNode[];
  concept_edges: GraphConceptEdge[];
  topic_edges: GraphTopicEdge[];
  concept_topic_edges: GraphConceptTopicEdge[];
  total_concepts: number;
};