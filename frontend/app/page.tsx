'use client';
import { useState } from 'react';
import { MainTab } from '@/lib/aeroStore';
import { AeroLayout } from '@/components/aero/Layout';
import { TabRead } from '@/components/aero/TabRead';
import { TabLearn } from '@/components/aero/TabLearn';
import { TabFix } from '@/components/aero/TabFix';
import { TabTest } from '@/components/aero/TabTest';
import { TabAutoQuant } from '@/components/aero/TabAutoQuant';
import { TabSettings } from '@/components/aero/TabSettings';
import { BootSequence } from '@/components/aero/BootSequence';
import { GlitchTransition } from '@/components/aero/GlitchTransition';

function TabContent({ tab }: { tab: MainTab }) {
  if (tab === 'read')      return <TabRead />;
  if (tab === 'learn')     return <TabLearn />;
  if (tab === 'fix')       return <TabFix />;
  if (tab === 'test')      return <TabTest />;
  if (tab === 'autoquant') return <TabAutoQuant />;
  if (tab === 'settings')  return <TabSettings />;
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
