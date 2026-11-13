'use client';

import { Editor } from '@/components/canvas/Editor';

export default function CanvasPage({ params }: { params: { id: string } }) {
  return <Editor graphId={params.id} />;
}
