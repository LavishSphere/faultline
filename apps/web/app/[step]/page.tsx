import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { StepView } from "@/components/StepView";
import { STEPS, findStep } from "@/lib/steps";

export const dynamicParams = false;

export function generateStaticParams() {
  return STEPS.map((s) => ({ step: s.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ step: string }> }): Promise<Metadata> {
  const { step } = await params;
  return { title: findStep(step)?.label ?? "Not found" };
}

export default async function StepPage({ params }: { params: Promise<{ step: string }> }) {
  const { step: slug } = await params;
  const step = findStep(slug);
  if (!step) notFound();
  return <StepView step={step} />;
}
