import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { LoadingCard } from '@/components/LoadingCard';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { fetchConceptDetail, fetchConceptRelations } from '../api';
import type { ConceptDetail, ConceptRelation } from '../types';

type ConceptDetailBundle = {
  concept: ConceptDetail;
  relations: ConceptRelation[];
};

type ConceptDetailViewProps = {
  conceptId: number;
  showHeader?: boolean;
  embedded?: boolean;
  onSelectConcept?: (conceptId: number) => void;
};

function qualityTone(quality?: number | null) {
  if (quality === 0 || quality === 1) return 'border-red-500/30 bg-red-500/10 text-red-100';
  if (quality === 2) return 'border-orange-500/30 bg-orange-500/10 text-orange-100';
  if (quality === 3) return 'border-amber-500/30 bg-amber-500/10 text-amber-100';
  if (quality === 4 || quality === 5) return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100';
  return 'border-white/10 bg-white/5 text-slate-300';
}

export function ConceptDetailPage() {
  const params = useParams<{ conceptId: string }>();
  const conceptId = Number(params.conceptId);

  return <ConceptDetailView conceptId={conceptId} />;
}

export function ConceptDetailView({ conceptId, showHeader = true, embedded = false, onSelectConcept }: ConceptDetailViewProps) {
  const isValidConceptId = Number.isInteger(conceptId) && conceptId > 0;

  const conceptQuery = useQuery<ConceptDetailBundle>({
    queryKey: ['concept-detail', conceptId],
    enabled: isValidConceptId,
    queryFn: async () => {
      const [concept, relations] = await Promise.all([
        fetchConceptDetail(conceptId),
        fetchConceptRelations(conceptId),
      ]);
      return { concept, relations };
    },
  });

  return (
    <section className="space-y-6">
        {showHeader ? (
          <div className="flex flex-col gap-3">
            <Badge className="w-fit">Concept</Badge>
            <div>
              <h2 className="text-3xl font-semibold tracking-tight text-white">Concept Detail</h2>
              <p className="mt-2 max-w-3xl text-sm text-slate-400">Review state, relations, remarks, and recent assessments for a single concept.</p>
            </div>
          </div>
        ) : null}

        {!isValidConceptId ? (
          <Card className="border-red-500/30 bg-red-500/10">
            <CardContent className="py-6 text-sm text-red-100">Invalid concept id.</CardContent>
          </Card>
        ) : null}

        {conceptQuery.isPending ? <LoadingCard label="Loading concept…" rows={3} /> : null}

        {conceptQuery.isError ? (
          <Card className="border-red-500/30 bg-red-500/10">
            <CardContent className="py-6 text-sm text-red-100">{(conceptQuery.error as Error).message}</CardContent>
          </Card>
        ) : null}

        {conceptQuery.data ? (
          <ConceptDetailContent
            concept={conceptQuery.data.concept}
            relations={conceptQuery.data.relations}
            embedded={embedded}
            onSelectConcept={onSelectConcept}
          />
        ) : null}
      </section>
  );
}

function ConceptDetailContent({ concept, relations, onSelectConcept }: ConceptDetailBundle & Pick<ConceptDetailViewProps, 'embedded' | 'onSelectConcept'>) {
  function renderConceptLink(conceptId: number, title: string, className: string) {
    if (onSelectConcept) {
      return (
        <button type="button" className={className} onClick={() => onSelectConcept(conceptId)}>
          {title}
        </button>
      );
    }

    return <Link className={className} to={`/concept/${conceptId}`}>{title}</Link>;
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">{concept.title}</CardTitle>
          <CardDescription>{concept.description || 'No description for this concept yet.'}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Badge>{concept.mastery_level}/100 mastery</Badge>
          <Badge variant="outline">{concept.review_count} reviews</Badge>
          <Badge variant="outline">{concept.interval_days || 1} day interval</Badge>
          {concept.topics.map((topic) => (
            <Link key={topic.id} className="inline-flex rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 transition-colors hover:border-white/20 hover:bg-white/10" to={`/topic/${topic.id}`}>{topic.title}</Link>
          ))}
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Review State</CardTitle>
              <CardDescription>Current scheduling and assessment state.</CardDescription>
            </CardHeader>
            <CardContent>
              <dl className="grid gap-4 sm:grid-cols-2">
                <div><dt className="text-xs uppercase tracking-[0.2em] text-slate-500">Next Review</dt><dd className="mt-1 text-sm text-slate-200">{concept.next_review_at || '—'}</dd></div>
                <div><dt className="text-xs uppercase tracking-[0.2em] text-slate-500">Last Reviewed</dt><dd className="mt-1 text-sm text-slate-200">{concept.last_reviewed_at || 'never'}</dd></div>
                <div><dt className="text-xs uppercase tracking-[0.2em] text-slate-500">Created</dt><dd className="mt-1 text-sm text-slate-200">{concept.created_at || '—'}</dd></div>
                <div><dt className="text-xs uppercase tracking-[0.2em] text-slate-500">Remark Updated</dt><dd className="mt-1 text-sm text-slate-200">{concept.remark_updated_at || '—'}</dd></div>
              </dl>
              {concept.remark_summary ? <div className="mt-4 rounded-2xl border border-sky-400/20 bg-sky-400/10 px-4 py-3 text-sm text-slate-100">{concept.remark_summary}</div> : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Recent Reviews</CardTitle>
              <CardDescription>Last few assessment results for this concept.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {concept.recent_reviews.length ? concept.recent_reviews.map((review) => (
                <div key={review.id} className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="text-sm font-medium text-slate-100">{review.question_asked || 'No question captured'}</div>
                    <Badge className={qualityTone(review.quality)} variant="outline">{review.quality ?? '?'} / 5</Badge>
                  </div>
                  <p className="mt-3 text-sm text-slate-300">{review.user_response || 'No answer captured.'}</p>
                  <div className="mt-3 text-xs text-slate-500">{review.llm_assessment || 'No assessment text.'} {review.reviewed_at ? `· ${review.reviewed_at}` : ''}</div>
                </div>
              )) : <p className="text-sm text-slate-400">No reviews yet.</p>}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Relations</CardTitle>
              <CardDescription>Connected concepts and their relation types.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {relations.length ? relations.map((relation) => (
                <div key={relation.id} className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    {renderConceptLink(relation.other_concept_id, relation.other_title, 'font-medium text-sky-200 transition-colors hover:text-sky-100')}
                    <Badge variant="outline">{relation.relation_type.replace(/_/g, ' ')}</Badge>
                    <Badge variant="outline">{relation.other_mastery}/100</Badge>
                  </div>
                  {relation.note ? <p className="mt-3 text-sm text-slate-400">{relation.note}</p> : null}
                </div>
              )) : <p className="text-sm text-slate-400">No related concepts yet.</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Remarks</CardTitle>
              <CardDescription>Latest saved notes for this concept.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {concept.remarks.length ? concept.remarks.map((remark) => (
                <div key={remark.id} className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
                  <p className="text-sm text-slate-200">{remark.content}</p>
                  <div className="mt-3 text-xs text-slate-500">{remark.created_at || '—'}</div>
                </div>
              )) : <p className="text-sm text-slate-400">No remarks yet.</p>}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}