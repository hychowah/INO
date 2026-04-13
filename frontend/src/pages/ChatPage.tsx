import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useInRouterContext } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { PageIntro } from '@/components/PageIntro';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { confirmPending, declinePending, fetchBootstrap, runChatAction, streamChat } from '../api';
import { AppLayout } from '../components/AppLayout';
import { resolveBackendHref } from '../lib/navigation';
import type { ActionBlock, ButtonAction, ChatEntry, ChatEnvelope } from '../types';

type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  variant?: 'default' | 'error';
  actions?: ActionBlock[];
};

type PendingAction = {
  action?: string;
  message?: string;
  params?: Record<string, unknown>;
  [key: string]: unknown;
};

const STORAGE_KEY = 'learning-agent-pending-action';

function loadPendingAction(): PendingAction | null {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as PendingAction) : null;
  } catch {
    return null;
  }
}

function formatMarker(content: string) {
  const match = /^\[(confirmed|declined):\s+(.+)\]$/.exec(content);
  if (!match) {
    return null;
  }
  const verb = match[1] === 'confirmed' ? 'Confirmed' : 'Declined';
  return `${verb}: ${match[2]}`;
}

function confirmationMarker(action: PendingAction | null) {
  if (!action?.action) {
    return '[confirmed]';
  }
  if (action.action === 'add_concept') {
    return '[confirmed: add concept]';
  }
  if (action.action === 'suggest_topic') {
    const title = typeof action.params?.title === 'string' ? action.params.title : 'topic';
    return `[confirmed: add topic "${title}"]`;
  }
  if (action.action === 'preference_update') {
    return '[confirmed: preference update]';
  }
  if (action.action === 'maintenance_review') {
    return '[confirmed: maintenance changes]';
  }
  if (action.action === 'taxonomy_review') {
    return '[confirmed: taxonomy changes]';
  }
  return `[confirmed: ${action.action}]`;
}

function declineMarker(action: PendingAction | null) {
  if (!action?.action) {
    return '[declined]';
  }
  if (action.action === 'add_concept') {
    return '[declined: add concept]';
  }
  if (action.action === 'suggest_topic') {
    const title = typeof action.params?.title === 'string' ? action.params.title : 'topic';
    return `[declined: add topic "${title}"]`;
  }
  if (action.action === 'preference_update') {
    return '[declined: preference update]';
  }
  if (action.action === 'maintenance_review') {
    return '[declined: maintenance changes]';
  }
  if (action.action === 'taxonomy_review') {
    return '[declined: taxonomy changes]';
  }
  return `[declined: ${action.action}]`;
}

function extractFollowupMessage(message: string, prefix?: string) {
  if (!prefix) {
    return message;
  }
  const normalizedPrefix = `${prefix}\n\n`;
  if (message.startsWith(normalizedPrefix)) {
    return message.slice(normalizedPrefix.length);
  }
  return message;
}

function renderInlineContent(content: string, renderConceptLink: (conceptId: string, key: string) => ReactNode) {
  return String(content)
    .split(/(\[concept:\d+\]|`[^`]+`|\*\*[^*]+\*\*)/g)
    .filter(Boolean)
    .map((part, index) => {
      const conceptMatch = /^\[concept:(\d+)\]$/.exec(part);
      if (conceptMatch) {
        return renderConceptLink(conceptMatch[1], `concept-${index}`);
      }

      const codeMatch = /^`([^`]+)`$/.exec(part);
      if (codeMatch) {
        return (
          <code
            className="rounded-md border border-white/10 bg-slate-950/80 px-1.5 py-0.5 font-mono text-[0.9em] text-sky-100"
            key={`code-${index}`}
          >
            {codeMatch[1]}
          </code>
        );
      }

      const strongMatch = /^\*\*([^*]+)\*\*$/.exec(part);
      if (strongMatch) {
        return (
          <strong className="font-semibold text-white" key={`strong-${index}`}>
            {strongMatch[1]}
          </strong>
        );
      }

      return <Fragment key={`text-${index}`}>{part}</Fragment>;
    });
}

function actionButtonVariant(style?: string) {
  return style === 'primary' ? 'default' : 'secondary';
}

function RichTextContent({ content, tone = 'default' }: { content: string; tone?: 'default' | 'error' | 'pending' }) {
  const inRouterContext = useInRouterContext();
  const normalized = String(content || '').replace(/\r\n/g, '\n').trim();

  if (!normalized) {
    return null;
  }

  const baseTextClass = 'text-slate-100';
  const linkClass =
    tone === 'error'
      ? 'font-medium text-red-100 underline decoration-red-200/40 underline-offset-4 hover:text-white'
      : 'font-medium text-sky-300 underline decoration-sky-400/40 underline-offset-4 hover:text-sky-200';

  function renderConceptLink(conceptId: string, key: string) {
    const path = `/concept/${conceptId}`;
    const label = `concept:${conceptId}`;

    if (inRouterContext) {
      return (
        <Link className={linkClass} key={key} to={path}>
          {label}
        </Link>
      );
    }

    return (
      <a className={linkClass} href={resolveBackendHref(path)} key={key}>
        {label}
      </a>
    );
  }

  return (
    <div className="space-y-3">
      {normalized.split(/\n{2,}/).map((block, blockIndex) => {
        const lines = block.split('\n').filter(Boolean);
        if (!lines.length) {
          return null;
        }

        if (lines.every((line) => /^[-*]\s+/.test(line))) {
          return (
            <ul className={`ml-5 list-disc space-y-1 text-sm leading-7 ${baseTextClass}`} key={`list-${blockIndex}`}>
              {lines.map((line, lineIndex) => (
                <li key={`item-${blockIndex}-${lineIndex}`}>
                  {renderInlineContent(line.replace(/^[-*]\s+/, ''), renderConceptLink)}
                </li>
              ))}
            </ul>
          );
        }

        if (lines.length === 1) {
          const headingMatch = /^(#{1,3})\s+(.+)$/.exec(lines[0]);
          if (headingMatch) {
            const headingContent = renderInlineContent(headingMatch[2], renderConceptLink);
            if (headingMatch[1].length === 1) {
              return (
                <h3 className={`text-base font-semibold tracking-tight ${baseTextClass}`} key={`heading-${blockIndex}`}>
                  {headingContent}
                </h3>
              );
            }
            if (headingMatch[1].length === 2) {
              return (
                <h4 className={`text-sm font-semibold uppercase tracking-[0.18em] ${baseTextClass}`} key={`heading-${blockIndex}`}>
                  {headingContent}
                </h4>
              );
            }
            return (
              <h5 className={`text-sm font-semibold ${baseTextClass}`} key={`heading-${blockIndex}`}>
                {headingContent}
              </h5>
            );
          }
        }

        return (
          <p className={`text-sm leading-7 ${baseTextClass}`} key={`paragraph-${blockIndex}`}>
            {lines.map((line, lineIndex) => (
              <Fragment key={`line-${blockIndex}-${lineIndex}`}>
                {lineIndex > 0 ? <br /> : null}
                {renderInlineContent(line, renderConceptLink)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const marker = formatMarker(message.content);
  const bubbleClass =
    message.role === 'user'
      ? 'max-w-[90%] rounded-[28px] bg-sky-500 px-4 py-3 text-sm text-slate-950 shadow-[0_20px_45px_rgba(14,165,233,0.22)]'
      : message.variant === 'error'
        ? 'max-w-[90%] rounded-[28px] border border-red-500/30 bg-red-500/12 px-4 py-3 text-sm text-red-100 shadow-[0_20px_45px_rgba(239,68,68,0.12)]'
        : 'max-w-[90%] rounded-[28px] border border-white/10 bg-slate-900/80 px-4 py-3 text-sm text-slate-100 shadow-[0_20px_45px_rgba(15,23,42,0.3)]';

  if (message.role === 'assistant' && !marker) {
    return (
      <div className={bubbleClass} role={message.variant === 'error' ? 'alert' : undefined}>
        <RichTextContent content={message.content} tone={message.variant === 'error' ? 'error' : 'default'} />
      </div>
    );
  }

  return (
    <div className={bubbleClass} role={message.variant === 'error' ? 'alert' : undefined}>
      <pre className="chat-pre">{marker || message.content}</pre>
    </div>
  );
}

function ActionRenderer({ actions, busy, onRun }: { actions: ActionBlock[]; busy: boolean; onRun: (action: ButtonAction['action']) => Promise<boolean> }) {
  const [hiddenBlocks, setHiddenBlocks] = useState<Set<number>>(() => new Set());
  const [hiddenItems, setHiddenItems] = useState<Set<string>>(() => new Set());

  async function handleActionClick(action: ButtonAction, blockIndex: number, itemId?: string) {
    const ok = await onRun(action.action);
    if (!ok) {
      return;
    }

    const uiEffect = action.ui_effect || (itemId ? 'remove_item' : 'remove_block');
    if (uiEffect === 'remove_block') {
      setHiddenBlocks((current) => new Set(current).add(blockIndex));
      return;
    }

    if (itemId) {
      setHiddenItems((current) => new Set(current).add(`${blockIndex}:${itemId}`));
    }
  }

  return (
    <div className="space-y-3 pt-3">
      {actions.map((block, index) => {
        if (hiddenBlocks.has(index)) {
          return null;
        }

        if (block.type === 'button_group') {
          return (
            <div className="space-y-3 rounded-[24px] border border-white/10 bg-slate-900/65 p-4" key={`group-${index}`}>
              {block.title ? <div className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-300">{block.title}</div> : null}
              <div className="flex flex-wrap gap-2">
                {block.buttons.map((button, buttonIndex) => (
                  <Button
                    disabled={busy}
                    key={buttonIndex}
                    onClick={() => void handleActionClick(button, index)}
                    size="sm"
                    type="button"
                    variant={actionButtonVariant(button.style)}
                  >
                    {button.label}
                  </Button>
                ))}
              </div>
            </div>
          );
        }

        if (block.type === 'proposal_review') {
          const visibleItems = block.items.filter((item) => !hiddenItems.has(`${index}:${item.id}`));
          if (!visibleItems.length) {
            return null;
          }

          return (
            <div className="space-y-4 rounded-[28px] border border-white/10 bg-slate-900/65 p-4" key={`proposal-${index}`}>
              <div className="text-sm font-semibold text-white">{block.title}</div>
              {block.description ? <div className="text-sm text-slate-300">{block.description}</div> : null}
              <div className="space-y-3">
                {visibleItems.map((item) => (
                  <div className="space-y-3 rounded-[22px] border border-white/8 bg-slate-950/55 p-4" key={item.id}>
                    <div className="text-sm font-medium text-slate-100">{item.label}</div>
                    {item.detail ? <div className="text-sm text-slate-400">{item.detail}</div> : null}
                    <div className="flex flex-wrap gap-2">
                      {item.buttons.map((button, buttonIndex) => (
                        <Button
                          disabled={busy}
                          key={buttonIndex}
                          onClick={() => void handleActionClick(button, index, item.id)}
                          size="sm"
                          type="button"
                          variant={actionButtonVariant(button.style)}
                        >
                          {button.label}
                        </Button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              {block.bulk_buttons?.length ? (
                <div className="flex flex-wrap gap-2 pt-1">
                  {block.bulk_buttons.map((button, buttonIndex) => (
                    <Button
                      disabled={busy}
                      key={buttonIndex}
                      onClick={() => void handleActionClick(button, index)}
                      size="sm"
                      type="button"
                      variant={actionButtonVariant(button.style)}
                    >
                      {button.label}
                    </Button>
                  ))}
                </div>
              ) : null}
            </div>
          );
        }

        return (
          <div className="space-y-3 rounded-[24px] border border-white/10 bg-slate-900/65 p-4" key={`choice-${index}`}>
            {block.title ? <div className="text-sm font-semibold text-white">{block.title}</div> : null}
            <div className="flex flex-wrap gap-2">
              {block.choices.map((choice, choiceIndex) => (
                <Button
                  disabled={busy}
                  key={choiceIndex}
                  onClick={() => void handleActionClick(choice, index)}
                  size="sm"
                  type="button"
                  variant={actionButtonVariant(choice.style)}
                >
                  {choice.label}
                </Button>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [commands, setCommands] = useState<Array<{ label: string; command: string }>>([]);
  const [draft, setDraft] = useState('');
  const [status, setStatus] = useState('');
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(() => loadPendingAction());
  const [pendingError, setPendingError] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const [requestInFlight, setRequestInFlight] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const requestInFlightRef = useRef(false);
  const messageIdRef = useRef(0);

  function createMessage(payload: Omit<Message, 'id'>): Message {
    const message = { id: `message-${messageIdRef.current}`, ...payload };
    messageIdRef.current += 1;
    return message;
  }

  function appendMessage(payload: Omit<Message, 'id'>): Message {
    const message = createMessage(payload);
    setMessages((current) => current.concat(message));
    return message;
  }

  function updateMessage(messageId: string, patch: Partial<Omit<Message, 'id'>>) {
    setMessages((current) => current.map((message) => (message.id === messageId ? { ...message, ...patch } : message)));
  }

  async function replayAssistantMessage(messageId: string, finalContent: string, variant: 'default' | 'error', actions?: ActionBlock[]) {
    const step = finalContent.length < 120 ? 6 : finalContent.length < 320 ? 12 : 24;

    for (let end = step; end < finalContent.length; end += step) {
      updateMessage(messageId, { content: finalContent.slice(0, end), variant });
      await new Promise((resolve) => window.setTimeout(resolve, 12));
    }

    updateMessage(messageId, { content: finalContent, variant, actions });
  }

  useEffect(() => {
    const input = inputRef.current;
    if (!input) {
      return;
    }

    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 220)}px`;
  }, [draft]);

  useEffect(() => {
    void fetchBootstrap().then((data) => {
      setMessages(
        data.history.map((entry: ChatEntry) =>
          createMessage({
            role: entry.role === 'assistant' ? 'assistant' : 'user',
            content: entry.content,
            variant: 'default'
          })
        )
      );
      setCommands(data.commands);
    });
  }, []);

  useEffect(() => {
    try {
      if (pendingAction) {
        window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(pendingAction));
      } else {
        window.sessionStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      // Ignore session storage failures in the browser.
    }
  }, [pendingAction]);

  useEffect(() => {
    const thread = threadRef.current;
    if (!thread) {
      return;
    }
    thread.scrollTop = thread.scrollHeight;
  }, [messages, pendingAction]);

  function setBusy(isBusy: boolean) {
    requestInFlightRef.current = isBusy;
    setRequestInFlight(isBusy);
  }

  function insertCommand(command: string) {
    setDraft((current) => `${current}${current && !current.endsWith(' ') ? ' ' : ''}${command}`);
    inputRef.current?.focus();
  }

  async function applyResponse(response: ChatEnvelope) {
    if (response.clear_history) {
      setMessages([]);
      setPendingAction(null);
      setPendingError('');
    }

    if (response.message) {
      appendMessage({ role: 'assistant', content: response.message, variant: response.type === 'error' ? 'error' : 'default', actions: response.actions });
    }

    if (response.type === 'pending_confirm' && response.pending_action) {
      setPendingAction(response.pending_action as PendingAction);
      setPendingError('');
    } else {
      setPendingAction(null);
      setPendingError('');
    }
  }

  async function handleSend() {
    const message = draft.trim();
    if (requestInFlightRef.current) {
      return;
    }
    if (!message) {
      return;
    }
    if (pendingAction && !message.startsWith('/')) {
      setStatus('Resolve the pending action before sending a new message.');
      return;
    }
    appendMessage({ role: 'user', content: message });
    setDraft('');
    setStatus('Connecting to the learning agent...');
    setPendingError('');
    setBusy(true);
    try {
      const response = await streamChat(message, {
        onStatus: (nextStatus) => {
          if (nextStatus) {
            setStatus(nextStatus);
          }
        }
      });

      if (response.clear_history) {
        setMessages([]);
        setPendingAction(null);
        setPendingError('');
      }

      if (response.message) {
        const assistantMessage = createMessage({
          role: 'assistant',
          content: '',
          variant: response.type === 'error' ? 'error' : 'default'
        });
        setMessages((current) => (response.clear_history ? [assistantMessage] : current.concat(assistantMessage)));
        setStatus('Streaming reply...');
        await replayAssistantMessage(
          assistantMessage.id,
          response.message,
          response.type === 'error' ? 'error' : 'default',
          response.actions
        );
      }

      if (response.type === 'pending_confirm' && response.pending_action) {
        setPendingAction(response.pending_action as PendingAction);
        setPendingError('');
      } else {
        setPendingAction(null);
        setPendingError('');
      }
    } catch (error) {
      appendMessage({ role: 'assistant', content: (error as Error).message, variant: 'error' });
    } finally {
      setBusy(false);
      setStatus('');
      inputRef.current?.focus();
    }
  }

  async function handleAction(action: ButtonAction['action']) {
    if (requestInFlightRef.current) {
      return false;
    }
    if (action.kind === 'dismiss') {
      return true;
    }

    setStatus('Running action...');
    setBusy(true);
    try {
      const response = await runChatAction(action);
      await applyResponse(response);
      return true;
    } catch (error) {
      appendMessage({ role: 'assistant', content: (error as Error).message, variant: 'error' });
      return false;
    } finally {
      setBusy(false);
      setStatus('');
      inputRef.current?.focus();
    }
  }

  async function handlePending(confirm: boolean) {
    if (!pendingAction || requestInFlightRef.current) {
      return;
    }
    setStatus(confirm ? 'Confirming action...' : 'Declining action...');
    setPendingError('');
    setBusy(true);
    try {
      const current = pendingAction;
      const response = confirm ? await confirmPending(current) : await declinePending(current);

      appendMessage({ role: 'user', content: confirm ? confirmationMarker(current) : declineMarker(current) });

      if (confirm) {
        const followup = extractFollowupMessage(response.message || '', current.message);
        if (followup) {
          appendMessage({ role: 'assistant', content: followup, variant: response.type === 'error' ? 'error' : 'default', actions: response.actions });
        }
      } else {
        appendMessage({ role: 'assistant', content: response.message || 'Declined.', variant: response.type === 'error' ? 'error' : 'default', actions: response.actions });
      }

      setPendingAction(null);
      setPendingError('');
    } catch (error) {
      setPendingError((error as Error).message || 'Could not resolve the pending action.');
    } finally {
      setBusy(false);
      setStatus('');
      inputRef.current?.focus();
    }
  }

  function handleComposerKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void handleSend();
    }
  }

  function handleComposerDrop(event: React.DragEvent<HTMLTextAreaElement>) {
    event.preventDefault();
    setDragActive(false);
    const command = event.dataTransfer.getData('text/plain').trim();
    if (command) {
      insertCommand(command);
    }
  }

  return (
    <AppLayout active="/chat">
      <section className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-5">
        <PageIntro
          eyebrow="Assistant"
          title="Chat"
          description="Agent conversation, action approvals, and command shortcuts in a fixed desktop workspace."
          aside={
            <>
              <Badge variant="outline">SSE streaming</Badge>
              <Badge variant="muted">{commands.length} quick commands</Badge>
            </>
          }
        />

        <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="flex min-h-0 flex-col gap-4">
            <Card className="min-h-0 flex-1 overflow-hidden">
              <CardContent className="h-full p-0">
                <div ref={threadRef} className="app-scrollbar flex h-full min-h-0 flex-col gap-4 overflow-y-auto bg-background/35 p-4 sm:p-5">
            {messages.length ? messages.map((message) => (
              <div className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`} key={message.id}>
                <div className="space-y-2">
                  <MessageBubble message={message} />
                  {message.role === 'assistant' && message.actions?.length ? (
                    <ActionRenderer actions={message.actions} busy={requestInFlight} onRun={handleAction} />
                  ) : null}
                </div>
              </div>
            )) : <div className="rounded-[24px] border border-dashed border-border bg-secondary/20 px-4 py-6 text-sm text-muted-foreground">No chat history yet. Start the conversation below.</div>}
                </div>
              </CardContent>
            </Card>

            {pendingAction ? (
              <Card className="shrink-0 border-amber-400/25 bg-amber-400/8">
                <CardContent className="space-y-4 py-6">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-semibold uppercase tracking-[0.24em] text-amber-100">Pending confirmation</div>
                    <Badge className="border-amber-300/20 bg-amber-300/10 text-amber-50" variant="outline">Action required</Badge>
                  </div>
                  <div className="rounded-[22px] border border-border/70 bg-background/45 px-4 py-3">
                    <RichTextContent content={pendingAction.message || 'Resolve the pending action before continuing.'} tone="pending" />
                  </div>
                  {pendingError ? <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-100">{pendingError}</div> : null}
                  <div className="flex flex-wrap gap-3">
                    <Button disabled={requestInFlight} onClick={() => void handlePending(true)}>Confirm</Button>
                    <Button variant="secondary" disabled={requestInFlight} onClick={() => void handlePending(false)}>Decline</Button>
                  </div>
                </CardContent>
              </Card>
            ) : null}

            <Card className="shrink-0">
              <CardContent className="space-y-4 py-5">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-semibold uppercase tracking-[0.24em] text-foreground">Composer</div>
                  <span className="text-xs text-muted-foreground">Enter to send, Shift+Enter for newline</span>
                </div>
                <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void handleSend(); }}>
                  <textarea
                    ref={inputRef}
                    className={`min-h-[3.5rem] w-full resize-none rounded-3xl border border-border bg-background/70 px-4 py-3 text-sm text-foreground outline-none transition focus:border-primary/50 focus:ring-2 focus:ring-primary/20${dragActive ? ' border-primary/60 ring-2 ring-primary/20' : ''}`}
                    disabled={requestInFlight}
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    onKeyDown={handleComposerKeyDown}
                    onDragOver={(event) => {
                      event.preventDefault();
                      setDragActive(true);
                    }}
                    onDragLeave={() => setDragActive(false)}
                    onDrop={handleComposerDrop}
                    rows={1}
                    placeholder="Ask a question, request a quiz, or tell the agent what you want to learn..."
                  />
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <span className="min-h-5 text-sm text-muted-foreground">{status}</span>
                    <Button disabled={requestInFlight} type="submit">{requestInFlight ? 'Working...' : 'Send'}</Button>
                  </div>
                </form>
              </CardContent>
            </Card>
          </div>

          <aside className="flex min-h-0 flex-col gap-4">
            <Card>
              <CardContent className="space-y-4 py-5">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-semibold uppercase tracking-[0.24em] text-foreground">Commands</div>
                  <span className="text-xs text-muted-foreground">Click or drag into the input</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {commands.map((item) => (
                    <Button
                      key={item.command}
                      variant="secondary"
                      size="sm"
                      className="rounded-full"
                      disabled={requestInFlight}
                      draggable
                      onClick={() => insertCommand(item.command)}
                      onDragStart={(event) => {
                        if (requestInFlight) {
                          event.preventDefault();
                          return;
                        }
                        event.dataTransfer.setData('text/plain', item.command);
                        event.dataTransfer.effectAllowed = 'copy';
                      }}
                    >
                      {item.label}
                    </Button>
                  ))}
                  {!commands.length ? <p className="text-sm text-muted-foreground">No suggested commands right now.</p> : null}
                </div>
              </CardContent>
            </Card>

            <Card className="flex-1 bg-panel-muted/65">
              <CardContent className="space-y-3 py-5 text-sm text-muted-foreground">
                <div className="text-sm font-semibold uppercase tracking-[0.24em] text-foreground">Notes</div>
                <p>The conversation thread now renders rich text and assistant actions with React components instead of injected HTML.</p>
                <p>Chat replies stream through the SSE endpoint and replay progressively in the thread once the final envelope arrives.</p>
              </CardContent>
            </Card>
          </aside>
        </div>
      </section>
    </AppLayout>
  );
}