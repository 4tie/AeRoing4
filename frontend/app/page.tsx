'use client';
import { useState } from 'react';
import { MainTab } from '@/lib/aeroStore';
import { AeroLayout } from '@/components/aero/Layout';
import { TabLearn } from '@/components/aero/TabLearn';
import { TabStrategies } from '@/components/aero/TabStrategies';
import { TabAutoQuant } from '@/components/aero/TabAutoQuant';
import { TabResults } from '@/components/aero/TabResults';
import { TabSettings } from '@/components/aero/TabSettings';
import { BootSequence } from '@/components/aero/BootSequence';
import { GlitchTransition } from '@/components/aero/GlitchTransition';

function TabContent({ tab }: { tab: MainTab }) {
  if (tab === 'learn')      return <TabLearn />;
  if (tab === 'strategies') return <TabStrategies />;
  if (tab === 'autoquant')  return <TabAutoQuant />;
  if (tab === 'results')    return <TabResults />;
  if (tab === 'settings')   return <TabSettings />;
  return null;
}

export default function AeroDashboard() {
  const [booted, setBooted] = useState(false);

  return (
    <>
      {!booted && <BootSequence onDone={() => setBooted(true)} />}
      <div style={{ opacity: booted ? 1 : 0, transition: 'opacity 0.5s ease 0.1s' }}>
        <AeroLayout>
          <GlitchTransition>
            {(tab) => <TabContent tab={tab} />}
          </GlitchTransition>
        </AeroLayout>
      </div>
    </>
  );
}
