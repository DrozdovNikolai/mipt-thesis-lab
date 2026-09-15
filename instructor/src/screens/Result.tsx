import { useState } from 'react';
import type { Client } from '../api/client';
import type { Receipt } from '../api/models';
import { submissionStatus } from '../api/training';
import { useAction } from '../hooks';
import { Action, Copy, Failure, Page, Panel, Title } from '../ui';

function statusTitle(receipt: Receipt) {
  switch (receipt.submissionStatus.toUpperCase()) {
    case 'COMPLETED': return 'Тренировка завершена';
    case 'FAILED': return 'Ошибка обработки';
    case 'PENDING': case 'PROCESSING': return 'Оценки обрабатываются';
    default: return receipt.submissionStatus;
  }
}

function Details({ receipt }: { receipt: Receipt }) {
  return <Panel><Copy muted>Тренировка № {receipt.trainingId}</Copy>
    <Title small>{statusTitle(receipt)}</Title>
    {receipt.assessmentsCompleted && <Copy>Сервер подтвердил итоговые оценки экипажа.</Copy>}
    <Failure message={receipt.submissionError || ''}/></Panel>;
}

export function Result({ client, initial, home }: { client: Client; initial: Receipt; home: () => void }) {
  const [receipt, setReceipt] = useState(initial);
  const action = useAction();
  return <Page><Title>Результат отправки</Title><Details receipt={receipt}/>
    <Failure message={action.error}/><Action secondary label={action.busy ? 'Обновляем…' : 'Обновить статус'} disabled={action.busy}
      onPress={() => action.run(async () => setReceipt(await submissionStatus(client, receipt.trainingId)))}/>
    <Action label="К сценариям" onPress={home}/>
  </Page>;
}

