#!/usr/bin/env ruby
# Adds the WHVWatch watchOS companion app target (single-target watch app,
# Xcode 14+ style) and embeds it into the WHV iOS app. Idempotent.
#
# Run:  cd ios && ruby Scripts/add_watch_target.rb

require 'xcodeproj'

PROJ_PATH = File.expand_path(File.join(__dir__, '..', 'WHV.xcodeproj'))
TARGET_NAME = 'WHVWatch'
APP_TARGET_NAME = 'WHV'
BUNDLE_ID = 'com.wagner-hausverwaltung.portal.watchkitapp'
APP_BUNDLE_ID = 'com.wagner-hausverwaltung.portal'
FOLDER = 'WHVWatch'

project = Xcodeproj::Project.open(PROJ_PATH)
app_target = project.targets.find { |t| t.name == APP_TARGET_NAME }
abort('Could not find WHV target') unless app_target

target = project.targets.find { |t| t.name == TARGET_NAME }
if target
  puts "#{TARGET_NAME} exists — re-scanning sources."
  group = project.main_group.find_subpath(TARGET_NAME, false)
  Dir.glob(File.join(__dir__, '..', FOLDER, '*.swift')).sort.each do |path|
    fn = File.basename(path)
    ref = group.files.find { |f| f.path == fn } || group.new_reference(fn)
    target.source_build_phase.add_file_reference(ref) unless target.source_build_phase.files_references.include?(ref)
  end
else
  puts "Adding #{TARGET_NAME} target …"
  group = project.main_group.new_group(TARGET_NAME, FOLDER)
  sources = Dir.glob(File.join(__dir__, '..', FOLDER, '*.swift')).sort.map { |p| group.new_reference(File.basename(p)) }
  assets = group.new_reference('Assets.xcassets')

  target = project.new_target(:application, TARGET_NAME, :watchos, '10.0')
  sources.each { |ref| target.source_build_phase.add_file_reference(ref) }
  target.resources_build_phase.add_file_reference(assets)

  target.build_configurations.each do |config|
    s = config.build_settings
    s['PRODUCT_NAME'] = '$(TARGET_NAME)'
    s['PRODUCT_BUNDLE_IDENTIFIER'] = BUNDLE_ID
    s['SDKROOT'] = 'watchos'
    s['WATCHOS_DEPLOYMENT_TARGET'] = '10.0'
    s['TARGETED_DEVICE_FAMILY'] = '4'
    s['SWIFT_VERSION'] = '5.0'
    s['CODE_SIGN_STYLE'] = 'Automatic'
    s['DEVELOPMENT_TEAM'] = 'K4KDX9GN74'
    s['SKIP_INSTALL'] = 'YES'
    s['ENABLE_PREVIEWS'] = 'YES'
    s['ASSETCATALOG_COMPILER_APPICON_NAME'] = 'AppIcon'
    s['ASSETCATALOG_COMPILER_GLOBAL_ACCENT_COLOR_NAME'] = 'AccentColor'
    s['GENERATE_INFOPLIST_FILE'] = 'YES'
    s['INFOPLIST_KEY_WKApplication'] = 'YES'
    s['INFOPLIST_KEY_WKCompanionAppBundleIdentifier'] = APP_BUNDLE_ID
    s['INFOPLIST_KEY_CFBundleDisplayName'] = 'WHV'
    s['INFOPLIST_KEY_UISupportedInterfaceOrientations'] = ['UIInterfaceOrientationPortrait', 'UIInterfaceOrientationPortraitUpsideDown']
    s['LD_RUNPATH_SEARCH_PATHS'] = ['$(inherited)', '@executable_path/Frameworks']
    s['MARKETING_VERSION'] = '1.3.6'
    s['CURRENT_PROJECT_VERSION'] = '61'
    s['SWIFT_EMIT_LOC_STRINGS'] = 'YES'
  end

  # Embed into the iOS app: Contents/Watch (dst_subfolder_spec 16 = wrapper).
  embed = app_target.build_phases.find do |p|
    p.is_a?(Xcodeproj::Project::Object::PBXCopyFilesBuildPhase) && p.name == 'Embed Watch Content'
  end
  embed ||= app_target.new_copy_files_build_phase('Embed Watch Content')
  embed.dst_subfolder_spec = '16'
  embed.dst_path = '$(CONTENTS_FOLDER_PATH)/Watch'
  unless embed.files_references.include?(target.product_reference)
    bf = embed.add_file_reference(target.product_reference)
    bf.settings = { 'ATTRIBUTES' => ['RemoveHeadersOnCopy'] }
  end
  app_target.add_dependency(target)
end

project.save
puts "✓ #{TARGET_NAME} ready."
