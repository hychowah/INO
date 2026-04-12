import { useEffect, useRef, useState } from 'react';
import { confirmPending, declinePending, fetchBootstrap, runChatAction, sendChat } from './api';
import type { ActionBlock, ButtonAction, ChatEntry, ChatEnvelope } from './types';

type Message = {
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
const DEV_SERVER_PORT = '5173';
const BACKEND_PORT = '8080';

type LocationLike = Pick<Location, 'protocol' | 'hostname' | 'port'>;

export function resolveBackendHref(path: string, locationLike: LocationLike = window.location) {
  if (locationLike.port !== DEV_SERVER_PORT) {
    return path;
  }
  return `${locationLike.protocol}//${locationLike.hostname}:${BACKEND_PORT}${path}`;
}

function loadPendingAction(): PendingAction | null {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as PendingAction) : null;
  } catch {
    return null;
  }
}

function escapeHtml(content: string) {
  return String(content)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
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

function formatInline(content: string) {
  return escapeHtml(content)
    .replace(/\[concept:(\d+)\]/g, (_, conceptId: string) => `<a class="chat-inline-link" href="${resolveBackendHref(`/concept/${conceptId}`)}">concept:${conceptId}</a>`)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
}

function renderRichText(content: string) {
  const normalized = String(content || '').replace(/\r\n/g, '\n').trim();
  if (!normalized) {
    return '';
  }

  return normalized
    .split(/\n{2,}/)
    .map((block) => {
      const lines = block.split('\n').filter(Boolean);
      if (!lines.length) {
        return '';
      }

      if (lines.every((line) => /^[-*]\s+/.test(line))) {
        return `<ul class="chat-list">${lines
          .map((line) => `<li>${formatInline(line.replace(/^[-*]\s+/, ''))}</li>`)
          .join('')}</ul>`;
      }

      if (lines.length === 1) {
        const headingMatch = /^(#{1,3})\s+(.+)$/.exec(lines[0]);
        if (headingMatch) {
          return `<p class="chat-heading chat-heading-${headingMatch[1].length}">${formatInline(headingMatch[2])}</p>`;
        }
      }

      return `<p>${lines.map(formatInline).join('<br>')}</p>`;
    })
    .join('');
}

function buttonClass(style?: string) {
  return style === 'primary' ? 'btn btn-primary' : 'btn';
}

function MessageBubble({ message }: { message: Message }) {
  const marker = formatMarker(message.content);
  const bubbleClass = message.variant === 'error' ? 'chat-bubble chat-bubble-error' : 'chat-bubble';

  if (message.role === 'assistant' && !marker) {
    return <div className={bubbleClass} role={message.variant === 'error' ? 'alert' : undefined} dangerouslySetInnerHTML={{ __html: renderRichText(message.content) }} />;
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
    <div className="chat-actions">
      {actions.map((block, index) => {
        if (hiddenBlocks.has(index)) {
          return null;
        }

        if (block.type === 'button_group') {
          return (
            <div className="chat-action-group" key={`group-${index}`}>
              {block.title ? <div className="chat-action-title">{block.title}</div> : null}
              <div className="chat-action-buttons">
                {block.buttons.map((button, buttonIndex) => (
                  <button key={buttonIndex} className={buttonClass(button.style)} disabled={busy} onClick={() => void handleActionClick(button, index)}>
                    {button.label}
                  </button>
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
            <div className="proposal-review" key={`proposal-${index}`}>
              <div className="proposal-review-title">{block.title}</div>
              {block.description ? <div className="proposal-review-description">{block.description}</div> : null}
              <div className="proposal-review-list">
                {visibleItems.map((item) => (
                  <div className="proposal-review-item" key={item.id}>
                    <div className="proposal-review-label">{item.label}</div>
                    {item.detail ? <div className="proposal-review-detail">{item.detail}</div> : null}
                    <div className="proposal-review-buttons">
                      {item.buttons.map((button, buttonIndex) => (
                        <button key={buttonIndex} className={buttonClass(button.style)} disabled={busy} onClick={() => void handleActionClick(button, index, item.id)}>
                          {button.label}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              {block.bulk_buttons?.length ? (
                <div className="proposal-review-bulk">
                  {block.bulk_buttons.map((button, buttonIndex) => (
                    <button key={buttonIndex} className={buttonClass(button.style)} disabled={busy} onClick={() => void handleActionClick(button, index)}>
                      {button.label}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          );
        }

        return (
          <div className="multiple-choice" key={`choice-${index}`}>
            {block.title ? <div className="multiple-choice-title">{block.title}</div> : null}
            <div className="multiple-choice-list">
              {block.choices.map((choice, choiceIndex) => (
                <button key={choiceIndex} className={buttonClass(choice.style)} disabled={busy} onClick={() => void handleActionClick(choice, index)}>
                  {choice.label}
                </button>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function App() {
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
        data.history.map((entry: ChatEntry) => ({
          role: entry.role === 'assistant' ? 'assistant' : 'user',
          content: entry.content,
          variant: 'default'
        }))
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
      setMessages((current) => current.concat({ role: 'assistant', content: response.message, variant: response.type === 'error' ? 'error' : 'default', actions: response.actions }));
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
    setMessages((current) => current.concat({ role: 'user', content: message }));
    setDraft('');
    setStatus('Waiting for the learning agent...');
    setPendingError('');
    setBusy(true);
    try {
      const response = await sendChat(message);
      await applyResponse(response);
    } catch (error) {
      setMessages((current) => current.concat({ role: 'assistant', content: (error as Error).message, variant: 'error' }));
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
      setMessages((current) => current.concat({ role: 'assistant', content: (error as Error).message, variant: 'error' }));
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

      setMessages((messages) => messages.concat({ role: 'user', content: confirm ? confirmationMarker(current) : declineMarker(current) }));

      if (confirm) {
        const followup = extractFollowupMessage(response.message || '', current.message);
        if (followup) {
          setMessages((messages) => messages.concat({ role: 'assistant', content: followup, variant: response.type === 'error' ? 'error' : 'default', actions: response.actions }));
        }
      } else {
        setMessages((messages) => messages.concat({ role: 'assistant', content: response.message || 'Declined.', variant: response.type === 'error' ? 'error' : 'default', actions: response.actions }));
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
    <div className="container chat-layout">
      <nav className="nav">
        <span className="brand">Learning Agent</span>
        <a href={resolveBackendHref('/')}>Dashboard</a>
        <a href="/chat" className="active">Chat</a>
        <a href={resolveBackendHref('/topics')}>Topics</a>
        <a href={resolveBackendHref('/concepts')}>Concepts</a>
        <a href={resolveBackendHref('/graph')}>Graph</a>
        <a href={resolveBackendHref('/reviews')}>Reviews</a>
        <a href={resolveBackendHref('/forecast')}>Forecast</a>
        <a href={resolveBackendHref('/actions')}>Activity</a>
      </nav>

      <div className="chat-page">
        <div className="chat-shell">
          <div className="chat-header">
            <h2>Chat</h2>
            <p className="chat-subtitle">Talk to the learning agent from the React chat shell.</p>
          </div>

          <div ref={threadRef} className="chat-thread">
            {messages.length ? messages.map((message, index) => (
              <div className={`chat-message chat-message-${message.role === 'user' ? 'user' : 'assistant'}`} key={index}>
                <MessageBubble message={message} />
                {message.role === 'assistant' && message.actions?.length ? (
                  <ActionRenderer actions={message.actions} busy={requestInFlight} onRun={handleAction} />
                ) : null}
              </div>
            )) : <div className="chat-empty">No chat history yet. Start the conversation below.</div>}
          </div>

          {pendingAction ? (
            <div className="chat-pending-card">
              <div className="chat-pending-title">Pending confirmation</div>
              <div className="chat-pending-summary" dangerouslySetInnerHTML={{ __html: renderRichText(pendingAction.message || 'Resolve the pending action before continuing.') }} />
              {pendingError ? <div className="chat-pending-error">{pendingError}</div> : null}
              <div className="chat-pending-actions">
                <button className="btn btn-primary" disabled={requestInFlight} onClick={() => void handlePending(true)}>Confirm</button>
                <button className="btn" disabled={requestInFlight} onClick={() => void handlePending(false)}>Decline</button>
              </div>
            </div>
          ) : null}

          <div className="chat-command-palette">
            <div className="chat-command-header">
              <span>Commands</span>
              <span className="chat-command-hint">Click or drag into the input</span>
            </div>
            <div className="chat-command-list">
              {commands.map((item) => (
                <button
                  key={item.command}
                  className="chat-command-chip"
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
                </button>
              ))}
            </div>
          </div>

          <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); void handleSend(); }}>
            <textarea
              ref={inputRef}
              className={`chat-input${dragActive ? ' chat-input-drop-target' : ''}`}
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
            <div className="chat-composer-actions">
              <span className="chat-status">{status}</span>
              <button className="btn btn-primary" disabled={requestInFlight} type="submit">{requestInFlight ? 'Working...' : 'Send'}</button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}