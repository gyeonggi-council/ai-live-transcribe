'use client';

import React, { createContext, useCallback, useContext, useState } from 'react';

interface BreadcrumbContextType {
  dynamicTitle: string | null;
  setTitle: (title: string | null) => void;
}

const BreadcrumbContext = createContext<BreadcrumbContextType | null>(null);

export function BreadcrumbProvider({ children }: { children: React.ReactNode }) {
  const [dynamicTitle, setDynamicTitle] = useState<string | null>(null);

  const setTitle = useCallback((title: string | null) => {
    setDynamicTitle(title);
  }, []);

  return (
    <BreadcrumbContext.Provider value={{ dynamicTitle, setTitle }}>
      {children}
    </BreadcrumbContext.Provider>
  );
}

export function useBreadcrumb() {
  const ctx = useContext(BreadcrumbContext);
  if (!ctx) throw new Error('useBreadcrumb must be used within BreadcrumbProvider');
  return ctx;
}
